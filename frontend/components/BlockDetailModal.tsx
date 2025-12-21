// Block Detail Modal Component
// Shows comprehensive details when a block cell is clicked

import React from 'react';
import { AssignmentOutput, BlockType, getBlockTypeColor } from '../types';

interface BlockDetailModalProps {
    assignment: AssignmentOutput | null;
    isOpen: boolean;
    onClose: () => void;
    onUnassign?: (blockId: string) => void;
    onLock?: (blockId: string) => void;
}

export default function BlockDetailModal({
    assignment,
    isOpen,
    onClose,
    onUnassign,
    onLock
}: BlockDetailModalProps) {
    if (!isOpen || !assignment) return null;

    const { block, driver_name, driver_id, day } = assignment;
    const blockColor = getBlockTypeColor(block.block_type as BlockType);

    const handleOverlayClick = (e: React.MouseEvent) => {
        if (e.target === e.currentTarget) {
            onClose();
        }
    };

    return (
        <div className="modal-overlay" onClick={handleOverlayClick}>
            <div className="modal-content">
                {/* Header */}
                <div className="modal-header" style={{ background: `linear-gradient(135deg, ${blockColor}, ${blockColor}dd)` }}>
                    <h2>{block.block_type.toUpperCase()} Block Details</h2>
                    <p className="header-subtitle">{day}</p>
                    <button className="close-btn" onClick={onClose} aria-label="Close modal">
                        ×
                    </button>
                </div>

                {/* Body */}
                <div className="modal-body">
                    {/* Driver Info */}
                    <section className="info-section">
                        <h3>👤 Driver</h3>
                        <div className="info-card">
                            <div className="info-row">
                                <span>Name:</span>
                                <span className="value">{driver_name}</span>
                            </div>
                            <div className="info-row">
                                <span>ID:</span>
                                <span className="value">{driver_id}</span>
                            </div>
                        </div>
                    </section>

                    {/* Block Metrics */}
                    <section className="info-section">
                        <h3>📊 Metrics</h3>
                        <div className="metrics-grid">
                            <div className="metric-card">
                                <div className="metric-value">{block.total_work_hours.toFixed(1)}h</div>
                                <div className="metric-label">Total Work</div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-value">{block.span_hours.toFixed(1)}h</div>
                                <div className="metric-label">Daily Span</div>
                            </div>
                            <div className="metric-card">
                                <div className="metric-value">{block.tours.length}</div>
                                <div className="metric-label">Tours</div>
                            </div>
                        </div>
                    </section>

                    {/* Timeline */}
                    <section className="info-section">
                        <h3>📅 Timeline</h3>
                        <div className="timeline">
                            {block.tours.map((tour, index) => (
                                <div key={tour.id} className="timeline-item">
                                    <div className="timeline-marker">{index + 1}</div>
                                    <div className="timeline-content">
                                        <div className="tour-header">
                                            <span className="tour-id">{tour.id}</span>
                                            <span className="tour-duration">({tour.duration_hours.toFixed(1)}h)</span>
                                        </div>
                                        <div className="tour-time">
                                            {tour.start_time} - {tour.end_time}
                                        </div>
                                        {tour.location && (
                                            <div className="tour-location">📍 {tour.location}</div>
                                        )}
                                        {tour.required_qualifications && tour.required_qualifications.length > 0 && (
                                            <div className="tour-quals">
                                                🎓 {tour.required_qualifications.join(', ')}
                                            </div>
                                        )}
                                    </div>
                                </div>
                            ))}
                        </div>
                    </section>
                </div>

                {/* Footer */}
                <div className="modal-footer">
                    {onLock && (
                        <button
                            className="btn-secondary"
                            onClick={() => onLock(block.id)}
                            title="Lock this assignment to prevent changes"
                        >
                            🔒 Lock
                        </button>
                    )}
                    {onUnassign && (
                        <button
                            className="btn-danger"
                            onClick={() => onUnassign(block.id)}
                            title="Remove this assignment"
                        >
                            🗑️ Unassign
                        </button>
                    )}
                    <button className="btn-primary" onClick={onClose}>
                        Close
                    </button>
                </div>
            </div>

            <style>{`
        .modal-overlay {
          position: fixed;
          top: 0;
          left: 0;
          right: 0;
          bottom: 0;
          background: rgba(0, 0, 0, 0.5);
          backdrop-filter: blur(4px);
          display: flex;
          align-items: center;
          justify-content: center;
          z-index: 2000;
          animation: fadeIn 200ms ease-out;
        }

        @keyframes fadeIn {
          from { opacity: 0; }
          to { opacity: 1; }
        }

        .modal-content {
          background: white;
          border-radius: 16px;
          width: 90%;
          max-width: 600px;
          max-height: 90vh;
          overflow: hidden;
          box-shadow: 0 20px 60px rgba(0,0,0,0.3);
          animation: slideUp 250ms cubic-bezier(0.34, 1.56, 0.64, 1);
        }

        @keyframes slideUp {
          from {
            transform: translateY(40px) scale(0.95);
            opacity: 0;
          }
          to {
            transform: translateY(0) scale(1);
            opacity: 1;
          }
        }

        .modal-header {
          padding: 24px;
          color: white;
          position: relative;
        }

        .modal-header h2 {
          margin: 0 0 4px 0;
          font-size: 24px;
          font-weight: 700;
        }

        .header-subtitle {
          margin: 0;
          font-size: 14px;
          opacity: 0.9;
        }

        .close-btn {
          position: absolute;
          top: 16px;
          right: 16px;
          background: rgba(255, 255, 255, 0.2);
          border: none;
          color: white;
          font-size: 32px;
          width: 40px;
          height: 40px;
          border-radius: 50%;
          cursor: pointer;
          transition: background 150ms;
          line-height: 1;
          padding: 0;
        }

        .close-btn:hover {
          background: rgba(255, 255, 255, 0.3);
        }

        .modal-body {
          padding: 24px;
          max-height: calc(90vh - 200px);
          overflow-y: auto;
        }

        .info-section {
          margin-bottom: 24px;
        }

        .info-section h3 {
          font-size: 16px;
          font-weight: 600;
          color: #334155;
          margin: 0 0 12px 0;
        }

        .info-card {
          background: #f8fafc;
          border-radius: 8px;
          padding: 16px;
        }

        .info-row {
          display: flex;
          justify-content: space-between;
          padding: 8px 0;
          font-size: 14px;
          color: #64748b;
        }

        .info-row:not(:last-child) {
          border-bottom: 1px solid #e2e8f0;
        }

        .info-row .value {
          font-weight: 600;
          color: #0f172a;
        }

        .metrics-grid {
          display: grid;
          grid-template-columns: repeat(3, 1fr);
          gap: 12px;
        }

        .metric-card {
          background: linear-gradient(135deg, #f8fafc, #f1f5f9);
          border-radius: 12px;
          padding: 20px;
          text-align: center;
          border: 1px solid #e2e8f0;
        }

        .metric-value {
          font-size: 28px;
          font-weight: 700;
          color: #6366f1;
          margin-bottom: 4px;
        }

        .metric-label {
          font-size: 12px;
          color: #64748b;
          text-transform: uppercase;
          letter-spacing: 0.05em;
        }

        .timeline {
          position: relative;
          padding-left: 32px;
        }

        .timeline::before {
          content: '';
          position: absolute;
          left: 10px;
          top: 0;
          bottom: 0;
          width: 2px;
          background: linear-gradient(to bottom, #6366f1, #a855f7);
        }

        .timeline-item {
          position: relative;
          margin-bottom: 20px;
        }

        .timeline-item:last-child {
          margin-bottom: 0;
        }

        .timeline-marker {
          position: absolute;
          left: -32px;
          top: 0;
          width: 24px;
          height: 24px;
          background: white;
          border: 3px solid #6366f1;
          border-radius: 50%;
          display: flex;
          align-items: center;
          justify-content: center;
          font-size: 11px;
          font-weight: 700;
          color: #6366f1;
          z-index: 1;
        }

        .timeline-content {
          background: #f8fafc;
          border-radius: 8px;
          padding: 12px;
        }

        .tour-header {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 6px;
        }

        .tour-id {
          font-weight: 600;
          color: #334155;
        }

        .tour-duration {
          font-size: 12px;
          color: #64748b;
          font-family: monospace;
        }

        .tour-time {
          font-family: monospace;
          font-size: 14px;
          color: #6366f1;
          margin-bottom: 6px;
        }

        .tour-location,
        .tour-quals {
          margin-top: 6px;
          font-size: 13px;
          color: #64748b;
        }

        .modal-footer {
          padding: 16px 24px;
          background: #f8fafc;
          border-top: 1px solid #e2e8f0;
          display: flex;
          gap: 12px;
          justify-content: flex-end;
        }

        .btn-primary,
        .btn-secondary,
        .btn-danger {
          padding: 10px 20px;
          border-radius: 8px;
          font-weight: 600;
          font-size: 14px;
          border: none;
          cursor: pointer;
          transition: all 150ms;
        }

        .btn-primary {
          background: linear-gradient(135deg, #6366f1, #a855f7);
          color: white;
        }

        .btn-primary:hover {
          transform: translateY(-2px);
          box-shadow: 0 4px 12px rgba(99, 102, 241, 0.3);
        }

        .btn-secondary {
          background: white;
          color: #334155;
          border: 1px solid #cbd5e1;
        }

        .btn-secondary:hover {
          background: #f8fafc;
        }

        .btn-danger {
          background: #ef4444;
          color: white;
        }

        .btn-danger:hover {
          background: #dc2626;
        }

        /* Responsive */
        @media (max-width: 640px) {
          .modal-content {
            width: 95%;
            max-height: 95vh;
          }

          .metrics-grid {
            grid-template-columns: 1fr;
          }

          .modal-footer {
            flex-direction: column;
          }

          .btn-primary,
          .btn-secondary,
          .btn-danger {
            width: 100%;
          }
        }
      `}</style>
        </div>
    );
}
