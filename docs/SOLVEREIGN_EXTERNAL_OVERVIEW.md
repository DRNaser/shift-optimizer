# SOLVEREIGN Platform Overview

> **Document Type**: External Stakeholder Summary
> **Last Updated**: 2026-01-07
> **Status**: Implementation Complete | Pilot-Ready
> **Verification**: See SOLVEREIGN_VERIFICATION_APPENDIX.md for source citations

---

## Executive Summary

SOLVEREIGN is a multi-tenant workforce scheduling platform that optimizes driver assignments for logistics operations. The system handles weekly tour schedules while enforcing configurable business rules and compliance constraints.

**Core Capability**: Given a weekly forecast of tours (shifts), SOLVEREIGN computes driver assignments that minimize total headcount while respecting rest periods, maximum work hours, and operational constraints.

**Implementation Status**: The platform is implemented and tested. Production deployment requires infrastructure provisioning and tenant onboarding.

---

## 1. What Problem Does SOLVEREIGN Solve?

### The Challenge
Logistics companies must assign drivers to hundreds of weekly tours while balancing:
- **Cost**: Minimize total drivers needed
- **Compliance**: Respect rest periods and maximum working hours
- **Operations**: Handle split shifts, overnight tours, and multi-depot assignments
- **Stability**: Avoid constant schedule changes that disrupt drivers

### The Solution
SOLVEREIGN automates this scheduling process:
1. **Import** weekly tour forecasts via CSV or API
2. **Optimize** driver assignments using constraint-based algorithms
3. **Audit** results against configurable compliance rules
4. **Lock** approved schedules to prevent unauthorized changes
5. **Export** assignments for payroll and dispatch systems

---

## 2. Key Features

### Multi-Tenant Architecture
- Each customer (tenant) operates in complete data isolation
- Database-level row security prevents cross-tenant data access
- Tenant-specific configurations for work hour limits and business rules

### Scheduling Optimization
- Automated driver assignment using OR-Tools constraint solver
- Configurable weekly hours cap (default: 55 hours per driver)
- Minimum rest period enforcement (default: 11 hours between shifts)
- Support for split shifts with configurable break requirements

### Compliance Auditing
Eight automated audit checks validate every schedule:
1. **Coverage**: Every tour has exactly one driver assigned
2. **Overlap**: No driver assigned to concurrent tours
3. **Rest**: Minimum rest between consecutive work days
4. **Regular Span**: Maximum shift duration for standard blocks
5. **Split Span**: Maximum duration for split shifts with break validation
6. **Fatigue**: Prevents consecutive high-intensity work patterns
7. **Reproducibility**: Same inputs produce identical outputs
8. **Sensitivity**: Detects input quality issues

### Plan Lifecycle Management
- **Draft**: Working version, can be modified
- **Locked**: Approved version, immutable via database triggers
- **Evidence Pack**: Exportable ZIP containing schedule, audit results, and integrity hashes

### Authentication & Access Control
- Enterprise single sign-on via Microsoft Entra ID
- Role-based access control (Viewer, Planner, Approver, Admin)
- API authentication via signed requests with replay protection

---

## 3. Technical Architecture

### Platform Components

| Component | Purpose |
|-----------|---------|
| **Backend API** | Python/FastAPI service handling business logic |
| **Database** | PostgreSQL with row-level security |
| **Solver Engine** | Constraint optimization for driver assignments |
| **Frontend** | React-based web application |

### Data Security

- **Tenant Isolation**: Row-level security policies on all data tables
- **Encryption**: TLS for data in transit
- **Audit Trail**: Append-only security event logging with hash chain
- **Immutability**: Database triggers prevent modification of locked schedules

### Integration Points

| Integration | Method |
|-------------|--------|
| **Forecast Import** | CSV upload or REST API |
| **Schedule Export** | CSV download or REST API |
| **Authentication** | Microsoft Entra ID (OAuth 2.0 / OIDC) |
| **Monitoring** | Health check endpoints for external monitoring |

---

## 4. Deployment Status

### Implementation Complete
- Core scheduling engine with constraint solver
- Multi-tenant database with row-level security
- Web-based user interface
- Authentication and authorization
- Audit framework with eight compliance checks
- Evidence pack generation

### Pilot-Ready Components
- Routing Pack for vehicle routing optimization (separate from workforce scheduling)
- Enterprise audit report generation
- KPI drift monitoring

### Infrastructure Requirements for Production
- PostgreSQL 16+ database instance
- Application server (containerized deployment supported)
- Microsoft Entra ID tenant for authentication
- Object storage for evidence packs (S3-compatible or Azure Blob)

---

## 5. Compliance Support

### Built-In Controls

| Control | Implementation |
|---------|----------------|
| **Data Isolation** | Database row-level security per tenant |
| **Access Logging** | Append-only audit trail with hash chain |
| **Change Prevention** | Database triggers block modification of locked records |
| **Reproducibility** | Deterministic solver with pinned dependencies |

### Evidence Exports

The platform generates evidence packs that can support compliance programs:
- **Audit Results**: JSON/Markdown reports of all compliance checks
- **Assignment Records**: Complete schedule data with timestamps
- **Integrity Hashes**: SHA256 hashes for tamper detection
- **Configuration Snapshots**: Solver settings and business rules applied

These exports provide documentation artifacts that organizations can incorporate into their compliance frameworks (GDPR record-keeping, SOC 2 evidence collection, ISO 27001 documentation).

---

## 6. Operational Characteristics

### Scheduling Performance
- Typical optimization: 1,000+ tours processed
- Solver execution: Configurable time limits (default: 60 seconds)
- Result caching for repeated queries

### Availability
- Stateless API design supports horizontal scaling
- Health check endpoints for load balancer integration
- Graceful degradation with service status indicators

### Monitoring
- Structured JSON logging
- Request tracing with correlation IDs
- Performance metrics for solver execution

---

## 7. Business Continuity

### Data Protection
- Point-in-time recovery via PostgreSQL
- Evidence packs stored in durable object storage
- Immutable locked schedules cannot be accidentally modified

### Change Management
- Database migrations tracked with version numbers
- Configuration changes logged to audit trail
- Rollback procedures documented

---

## 8. Stakeholder Quick Reference

### For Operations Leaders
- Reduces manual scheduling effort
- Enforces consistent compliance rules
- Provides auditable schedule history

### For Finance
- Optimizes driver headcount (cost minimization objective)
- Tracks full-time vs. part-time allocation
- Exports integrate with payroll systems

### For IT / Security
- Standard authentication (Entra ID)
- Database-level multi-tenancy
- Evidence exports for audit requirements

### For Legal / Compliance
- Configurable working hour limits
- Automated compliance checking
- Immutable records with hash verification

---

## 9. Limitations and Scope

### Current Scope
- Weekly tour scheduling for logistics drivers
- Single optimization run per forecast version
- Web-based interface (no mobile app)

### Out of Scope
- Real-time route optimization (planned as separate module)
- Driver mobile application
- Payroll calculation (export only)
- Automatic regulatory compliance certification

### Configuration Required
- Weekly hours cap is configurable per tenant (not a fixed legal requirement)
- Rest period minimums are configurable
- Split shift rules are configurable

---

## 10. Next Steps for Evaluation

1. **Technical Review**: Request access to verification appendix for source citations
2. **Demo Environment**: Coordinate sandbox tenant provisioning
3. **Integration Assessment**: Review API documentation for forecast import/export
4. **Security Review**: Request security architecture documentation

---

## Document Information

| Item | Value |
|------|-------|
| **Classification** | External |
| **Audience** | COO, CFO, Legal, Partner IT |
| **Verification** | SOLVEREIGN_VERIFICATION_APPENDIX.md |
| **Contact** | [Project Technical Lead] |

*All technical claims in this document are verified against the source code repository. See the Verification Appendix for file path and line number citations.*
