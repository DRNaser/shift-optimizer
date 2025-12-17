import { useState, useRef, type DragEvent, type ChangeEvent } from 'react';

interface FileUploadProps {
    onFileSelect: (content: string, fileName: string) => void;
}

export function FileUpload({ onFileSelect }: FileUploadProps) {
    const [isDragging, setIsDragging] = useState(false);
    const [fileName, setFileName] = useState<string | null>(null);
    const inputRef = useRef<HTMLInputElement>(null);

    const handleDragOver = (e: DragEvent) => {
        e.preventDefault();
        setIsDragging(true);
    };

    const handleDragLeave = () => {
        setIsDragging(false);
    };

    const handleDrop = (e: DragEvent) => {
        e.preventDefault();
        setIsDragging(false);
        const file = e.dataTransfer.files[0];
        if (file) readFile(file);
    };

    const handleChange = (e: ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (file) readFile(file);
    };

    const readFile = (file: File) => {
        setFileName(file.name);
        const reader = new FileReader();
        reader.onload = (e) => {
            const content = e.target?.result as string;
            onFileSelect(content, file.name);
        };
        reader.readAsText(file);
    };

    const zoneClass = `upload-zone ${isDragging ? 'active' : ''} ${fileName ? 'has-file' : ''}`;

    return (
        <div
            className={zoneClass}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
            onClick={() => inputRef.current?.click()}
        >
            <input
                ref={inputRef}
                type="file"
                accept=".csv"
                onChange={handleChange}
                style={{ display: 'none' }}
            />
            <svg className="upload-icon" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
            {fileName ? (
                <div className="upload-text">
                    <strong>✓ {fileName}</strong>
                    <p className="text-muted">Click to change file</p>
                </div>
            ) : (
                <div className="upload-text">
                    <strong>Click to upload</strong> or drag and drop
                    <p className="text-muted">CSV file (forecast input)</p>
                </div>
            )}
        </div>
    );
}
