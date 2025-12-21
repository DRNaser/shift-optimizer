'use client';

import { useState, useEffect, useRef } from 'react';
import { useRouter } from 'next/navigation';
import {
    getConfigSchema,
    createRun,
    type ConfigSchema,
    type ConfigField,
    type RunCreateRequest
} from '@/utils/api';
import { importToursFromCsvFile, type CsvImportResult } from '@/utils/importToursCsv';

// Sample tours for testing
const SAMPLE_TOURS = [
    { id: "T001", day: "monday", start_time: "06:00", end_time: "10:00" },
    { id: "T002", day: "monday", start_time: "10:30", end_time: "14:30" },
    { id: "T003", day: "tuesday", start_time: "07:00", end_time: "11:00" },
];

export default function SetupPage() {
    const router = useRouter();
    const [schema, setSchema] = useState<ConfigSchema | null>(null);
    const [loading, setLoading] = useState(true);
    const [submitting, setSubmitting] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Form state
    const [weekStart, setWeekStart] = useState(() => {
        const today = new Date();
        const monday = new Date(today);
        monday.setDate(today.getDate() - today.getDay() + 1);
        return monday.toISOString().split('T')[0];
    });
    const [toursJson, setToursJson] = useState(JSON.stringify(SAMPLE_TOURS, null, 2));
    const [toursError, setToursError] = useState<string | null>(null);
    const [timeBudget, setTimeBudget] = useState(30);
    const [seed, setSeed] = useState<number | null>(42);
    const [configOverrides, setConfigOverrides] = useState<Record<string, any>>({});

    // CSV Import state
    const csvFileRef = useRef<HTMLInputElement>(null);
    const [csvInfo, setCsvInfo] = useState<string>('');
    const [csvWarnings, setCsvWarnings] = useState<string[]>([]);

    // Load schema on mount
    useEffect(() => {
        async function loadSchema() {
            try {
                const data = await getConfigSchema();
                setSchema(data);

                // Initialize defaults from schema
                const defaults: Record<string, any> = {};
                data.groups.forEach(group => {
                    group.fields.forEach(field => {
                        if (field.editable && field.default !== null) {
                            defaults[field.key] = field.default;
                        }
                    });
                });
                setConfigOverrides(defaults);
            } catch (e) {
                setError(`Failed to load config schema: ${e}`);
            } finally {
                setLoading(false);
            }
        }
        loadSchema();
    }, []);

    // Parse tours JSON
    const parsedTours = (() => {
        try {
            const parsed = JSON.parse(toursJson);
            if (!Array.isArray(parsed)) {
                throw new Error('Tours must be an array');
            }
            return { valid: true, tours: parsed, error: null };
        } catch (e: any) {
            return { valid: false, tours: [], error: e.message };
        }
    })();

    // Handle JSON file upload
    const handleJsonFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        const reader = new FileReader();
        reader.onload = (ev) => {
            const content = ev.target?.result as string;
            setToursJson(content);
            setCsvInfo('');
            setCsvWarnings([]);
        };
        reader.readAsText(file);
    };

    // Handle CSV file upload
    const handleCsvUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        e.target.value = ''; // allow re-upload same file
        if (!file) return;

        setCsvInfo('Parsing CSV…');
        setCsvWarnings([]);
        setToursError(null);

        try {
            const { tours, stats, warnings } = await importToursFromCsvFile(file);
            setToursJson(JSON.stringify(tours, null, 2));
            setCsvInfo(`✅ CSV importiert: ${stats.toursCount} Tours / ${stats.totalHours}h`);
            setCsvWarnings(warnings);
        } catch (err: any) {
            setCsvInfo(`❌ CSV Import fehlgeschlagen: ${err?.message ?? String(err)}`);
            setCsvWarnings([]);
        }
    };

    // Update config override
    const updateOverride = (key: string, value: any) => {
        setConfigOverrides(prev => ({ ...prev, [key]: value }));
    };

    // Build request
    const buildRequest = (): RunCreateRequest => {
        // Only include overrides that differ from defaults
        const overrides: Record<string, any> = {};
        if (schema) {
            schema.groups.forEach(group => {
                group.fields.forEach(field => {
                    if (field.editable && configOverrides[field.key] !== field.default) {
                        overrides[field.key] = configOverrides[field.key];
                    }
                });
            });
        }

        return {
            week_start: weekStart,
            tours: parsedTours.tours,
            run: {
                seed: seed ?? undefined,
                time_budget_seconds: timeBudget,
                config_overrides: overrides
            }
        };
    };

    // Submit
    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();

        if (!parsedTours.valid) {
            setToursError(parsedTours.error);
            return;
        }

        setSubmitting(true);
        setError(null);

        try {
            const request = buildRequest();
            const result = await createRun(request);
            router.push(`/runs/${result.run_id}`);
        } catch (e: any) {
            setError(e.message || 'Failed to create run');
        } finally {
            setSubmitting(false);
        }
    };

    // Render field control
    const renderFieldControl = (field: ConfigField) => {
        const value = configOverrides[field.key] ?? field.default;
        const isLocked = !field.editable;

        if (field.type === 'bool') {
            return (
                <div className="flex items-center gap-3">
                    <button
                        type="button"
                        onClick={() => !isLocked && updateOverride(field.key, !value)}
                        className={`toggle-container ${value ? 'active' : 'inactive'} ${isLocked ? 'disabled' : ''}`}
                        disabled={isLocked}
                    >
                        <span className="toggle-dot" />
                    </button>
                    <span className="text-sm">{value ? 'Enabled' : 'Disabled'}</span>
                </div>
            );
        }

        if (field.type === 'float' || field.type === 'int') {
            return (
                <div className="flex items-center gap-4">
                    <input
                        type="range"
                        min={field.min ?? 0}
                        max={field.max ?? 100}
                        step={field.type === 'int' ? 1 : 0.01}
                        value={value as number}
                        onChange={(e) => !isLocked && updateOverride(field.key,
                            field.type === 'int' ? parseInt(e.target.value) : parseFloat(e.target.value)
                        )}
                        disabled={isLocked}
                        className="slider flex-1"
                    />
                    <span className="text-sm font-mono w-16 text-right">{value}</span>
                </div>
            );
        }

        return (
            <input
                type="text"
                value={String(value)}
                onChange={(e) => !isLocked && updateOverride(field.key, e.target.value)}
                disabled={isLocked}
                className="input"
            />
        );
    };

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-[400px]">
                <div className="text-muted-foreground">Loading configuration schema...</div>
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto">
            <div className="mb-8">
                <h1 className="text-3xl font-bold mb-2">Run Setup</h1>
                <p className="text-muted-foreground">Configure and start a new optimization run</p>
            </div>

            {error && (
                <div className="mb-6 p-4 bg-destructive/10 text-destructive rounded-lg">
                    {error}
                </div>
            )}

            <form onSubmit={handleSubmit} className="space-y-8">
                {/* Basic Settings */}
                <div className="card">
                    <h2 className="text-lg font-semibold mb-4">Basic Settings</h2>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                        <div>
                            <label className="block text-sm font-medium mb-2">Week Start</label>
                            <input
                                type="date"
                                value={weekStart}
                                onChange={(e) => setWeekStart(e.target.value)}
                                className="input"
                                required
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-2">Time Budget (seconds)</label>
                            <input
                                type="number"
                                min={5}
                                max={600}
                                value={timeBudget}
                                onChange={(e) => setTimeBudget(parseInt(e.target.value))}
                                className="input"
                            />
                        </div>
                        <div>
                            <label className="block text-sm font-medium mb-2">Seed (optional)</label>
                            <input
                                type="number"
                                value={seed ?? ''}
                                onChange={(e) => setSeed(e.target.value ? parseInt(e.target.value) : null)}
                                placeholder="Random"
                                className="input"
                            />
                        </div>
                    </div>
                </div>

                {/* Tours Input */}
                <div className="card">
                    <div className="flex items-center justify-between mb-4">
                        <h2 className="text-lg font-semibold">Tours</h2>
                        <div className="flex gap-2">
                            <button
                                type="button"
                                className="btn-primary btn-sm"
                                onClick={() => csvFileRef.current?.click()}
                            >
                                Upload CSV
                            </button>
                            <input
                                ref={csvFileRef}
                                type="file"
                                accept=".csv,text/csv"
                                onChange={handleCsvUpload}
                                className="hidden"
                            />
                            <label className="btn-secondary btn-sm cursor-pointer">
                                <input
                                    type="file"
                                    accept=".json"
                                    onChange={handleJsonFileUpload}
                                    className="hidden"
                                />
                                Upload JSON
                            </label>
                        </div>
                    </div>

                    {/* CSV Import Status */}
                    {csvInfo && (
                        <div className={`mb-4 text-sm p-3 rounded-lg ${csvInfo.startsWith('✅') ? 'bg-green-500/10 text-green-400' :
                                csvInfo.startsWith('❌') ? 'bg-red-500/10 text-red-400' :
                                    'bg-blue-500/10 text-blue-400'
                            }`}>
                            {csvInfo}
                        </div>
                    )}
                    {csvWarnings.length > 0 && (
                        <div className="mb-4 text-xs text-yellow-500 space-y-1">
                            {csvWarnings.map((w, i) => (
                                <div key={i}>⚠️ {w}</div>
                            ))}
                        </div>
                    )}

                    <textarea
                        value={toursJson}
                        onChange={(e) => {
                            setToursJson(e.target.value);
                            setToursError(null);
                            setCsvInfo('');
                            setCsvWarnings([]);
                        }}
                        className="textarea font-mono text-sm h-64"
                        placeholder="Paste tours JSON here..."
                    />

                    {(toursError || parsedTours.error) && (
                        <p className="mt-2 text-sm text-destructive">{toursError || parsedTours.error}</p>
                    )}

                    {parsedTours.valid && (
                        <p className="mt-2 text-sm text-muted-foreground">
                            {parsedTours.tours.length} tours parsed successfully
                        </p>
                    )}
                </div>

                {/* Config Schema Groups */}
                {schema?.groups.map(group => (
                    <div key={group.id} className="card">
                        <h2 className="text-lg font-semibold mb-4">{group.label}</h2>
                        <div className="space-y-4">
                            {group.fields.map(field => (
                                <div key={field.key} className="flex flex-col gap-2">
                                    <div className="flex items-center gap-2">
                                        <label className="text-sm font-medium">{field.key}</label>
                                        {field.locked_reason && (
                                            <span className="tooltip">
                                                <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded">
                                                    LOCKED
                                                </span>
                                                <span className="tooltip-text">{field.locked_reason}</span>
                                            </span>
                                        )}
                                    </div>
                                    <p className="text-xs text-muted-foreground">{field.description}</p>
                                    {renderFieldControl(field)}
                                </div>
                            ))}
                        </div>
                    </div>
                ))}

                {/* Request Preview */}
                <div className="card">
                    <h2 className="text-lg font-semibold mb-4">Request Preview</h2>
                    <pre className="bg-muted p-4 rounded-lg text-xs font-mono overflow-auto max-h-64">
                        {JSON.stringify(buildRequest(), null, 2)}
                    </pre>
                </div>

                {/* Submit */}
                <div className="flex justify-end gap-4">
                    <button type="button" className="btn-secondary" onClick={() => window.location.reload()}>
                        Reset
                    </button>
                    <button
                        type="submit"
                        disabled={!parsedTours.valid || submitting}
                        className="btn-primary"
                    >
                        {submitting ? 'Starting...' : 'Start Run'}
                    </button>
                </div>
            </form>
        </div>
    );
}
