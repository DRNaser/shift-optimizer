/**
 * SOLVEREIGN - Data Quality Regression Tests
 *
 * Verifies that missing block data:
 * 1. Does NOT crash the system
 * 2. IS surfaced to the user (not silently dropped)
 *
 * Run: npx ts-node lib/__tests__/data-quality.regression.ts
 */

import { analyzeAssignments, assignmentsToDriverRows } from '../export';
import type { AssignmentOutput } from '../api';

// =============================================================================
// TEST DATA
// =============================================================================

const VALID_ASSIGNMENT: AssignmentOutput = {
  driver_id: 'D001',
  driver_name: 'Max Mustermann',
  day: 'MONDAY',
  block: {
    id: 'B001',
    day: 'MONDAY',
    block_type: '3er',
    tours: [
      { id: 'T001', day: 'MONDAY', start_time: '06:00', end_time: '10:00', duration_hours: 4.0 },
      { id: 'T002', day: 'MONDAY', start_time: '12:00', end_time: '16:00', duration_hours: 4.0 },
    ],
    total_work_hours: 8.0,
    driver_id: 'D001',
    span_hours: 10.0,
    pause_zone: 'OPTIMAL',
  },
};

const MISSING_BLOCK_ASSIGNMENT: AssignmentOutput = {
  driver_id: 'D002',
  driver_name: 'Anna Schmidt',
  day: 'TUESDAY',
  block: null as unknown as AssignmentOutput['block'], // Simulates backend returning null
};

const UNDEFINED_BLOCK_ASSIGNMENT: AssignmentOutput = {
  driver_id: 'D003',
  driver_name: 'Hans Weber',
  day: 'WEDNESDAY',
  block: undefined as unknown as AssignmentOutput['block'], // Simulates missing field
};

// =============================================================================
// TEST CASES
// =============================================================================

interface TestResult {
  name: string;
  passed: boolean;
  error?: string;
}

const results: TestResult[] = [];

function test(name: string, fn: () => void): void {
  try {
    fn();
    results.push({ name, passed: true });
    console.log(`  ✓ ${name}`);
  } catch (err) {
    const error = err instanceof Error ? err.message : String(err);
    results.push({ name, passed: false, error });
    console.log(`  ✗ ${name}`);
    console.log(`    Error: ${error}`);
  }
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(message);
  }
}

// =============================================================================
// TEST: analyzeAssignments
// =============================================================================

console.log('\n[TEST] analyzeAssignments()\n');

test('does NOT crash with null block', () => {
  const assignments = [VALID_ASSIGNMENT, MISSING_BLOCK_ASSIGNMENT];
  const report = analyzeAssignments(assignments);
  assert(report !== null, 'Should return a report');
});

test('does NOT crash with undefined block', () => {
  const assignments = [VALID_ASSIGNMENT, UNDEFINED_BLOCK_ASSIGNMENT];
  const report = analyzeAssignments(assignments);
  assert(report !== null, 'Should return a report');
});

test('does NOT crash with all missing blocks', () => {
  const assignments = [MISSING_BLOCK_ASSIGNMENT, UNDEFINED_BLOCK_ASSIGNMENT];
  const report = analyzeAssignments(assignments);
  assert(report !== null, 'Should return a report');
});

test('surfaces missing block count accurately', () => {
  const assignments = [VALID_ASSIGNMENT, MISSING_BLOCK_ASSIGNMENT, UNDEFINED_BLOCK_ASSIGNMENT];
  const report = analyzeAssignments(assignments);

  assert(report.total_assignments === 3, `Expected 3 total, got ${report.total_assignments}`);
  assert(report.missing_block_count === 2, `Expected 2 missing, got ${report.missing_block_count}`);
  assert(report.valid_assignments === 1, `Expected 1 valid, got ${report.valid_assignments}`);
  assert(report.has_data_loss === true, 'Should flag has_data_loss');
});

test('returns empty missing list for all-valid data', () => {
  const assignments = [VALID_ASSIGNMENT];
  const report = analyzeAssignments(assignments);

  assert(report.missing_block_count === 0, 'Should have 0 missing');
  assert(report.has_data_loss === false, 'Should NOT flag has_data_loss');
  assert(report.missing_block_ids.length === 0, 'Should have empty missing list');
});

test('includes driver info in missing block report', () => {
  const assignments = [MISSING_BLOCK_ASSIGNMENT];
  const report = analyzeAssignments(assignments);

  assert(report.missing_block_ids.length === 1, 'Should have 1 missing entry');
  assert(report.missing_block_ids[0].driver_id === 'D002', 'Should include driver_id');
  assert(report.missing_block_ids[0].driver_name === 'Anna Schmidt', 'Should include driver_name');
  assert(report.missing_block_ids[0].day === 'TUESDAY', 'Should include day');
});

// =============================================================================
// TEST: assignmentsToDriverRows
// =============================================================================

console.log('\n[TEST] assignmentsToDriverRows()\n');

test('does NOT crash with missing blocks in matrix conversion', () => {
  const assignments = [VALID_ASSIGNMENT, MISSING_BLOCK_ASSIGNMENT, UNDEFINED_BLOCK_ASSIGNMENT];
  const result = assignmentsToDriverRows(assignments);
  assert(result !== null, 'Should return a result');
  assert(result.rows !== null, 'Should have rows array');
});

test('marks missing data with visual indicator in rows', () => {
  const assignments = [MISSING_BLOCK_ASSIGNMENT];
  const result = assignmentsToDriverRows(assignments);

  assert(result.rows.length === 1, 'Should have 1 driver row');
  const row = result.rows[0];
  assert(row.tuesday.includes('[?]'), `Tuesday should show missing indicator, got: ${row.tuesday}`);
  assert(row.tuesday.includes('DATEN FEHLEN'), `Tuesday should show missing text, got: ${row.tuesday}`);
});

test('returns quality report with matrix conversion', () => {
  const assignments = [VALID_ASSIGNMENT, MISSING_BLOCK_ASSIGNMENT];
  const result = assignmentsToDriverRows(assignments);

  assert(result.qualityReport !== null, 'Should include quality report');
  assert(result.qualityReport.missing_block_count === 1, 'Report should show 1 missing');
});

test('preserves valid data alongside missing data', () => {
  const assignments = [VALID_ASSIGNMENT, MISSING_BLOCK_ASSIGNMENT];
  const result = assignmentsToDriverRows(assignments);

  // Find the valid driver
  const validRow = result.rows.find(r => r.driverId === 'D001');
  if (!validRow) {
    throw new Error('Should include valid driver');
  }
  assert(validRow.monday.includes('3er'), `Monday should have block type, got: ${validRow.monday}`);
  assert(validRow.totalHours === 8.0, `Should have correct hours, got: ${validRow.totalHours}`);
});

// =============================================================================
// TEST: Edge cases
// =============================================================================

console.log('\n[TEST] Edge cases\n');

test('handles empty assignment array', () => {
  const report = analyzeAssignments([]);
  assert(report.total_assignments === 0, 'Should handle empty array');
  assert(report.has_data_loss === false, 'Empty is not data loss');
});

test('handles assignment with empty block object', () => {
  const emptyBlockAssignment: AssignmentOutput = {
    driver_id: 'D004',
    driver_name: 'Test User',
    day: 'FRIDAY',
    block: {} as AssignmentOutput['block'], // Empty object - should be treated as invalid
  };

  // Empty object is truthy but has no data - this tests defensive handling
  const report = analyzeAssignments([emptyBlockAssignment]);
  // Note: Current impl treats empty object as valid - this documents behavior
  assert(report !== null, 'Should not crash');
});

// =============================================================================
// SUMMARY
// =============================================================================

console.log('\n' + '='.repeat(60));
console.log(' DATA QUALITY REGRESSION TEST SUMMARY');
console.log('='.repeat(60));

const passed = results.filter(r => r.passed).length;
const failed = results.filter(r => !r.passed).length;

console.log(`\n  Total:  ${results.length}`);
console.log(`  Passed: ${passed}`);
console.log(`  Failed: ${failed}`);

if (failed > 0) {
  console.log('\n  FAILURES:');
  results.filter(r => !r.passed).forEach(r => {
    console.log(`    - ${r.name}: ${r.error}`);
  });
  console.log('\n');
  process.exit(1);
}

console.log('\n  All data quality regression tests PASSED');
console.log('  Missing block data is surfaced, not silently dropped.\n');
process.exit(0);
