# =============================================================================
# Routing Pack - Travel Time Services
# =============================================================================
# Pluggable travel time providers (StaticMatrix -> OSRM -> Google).
# V3.5: Added TTMeta for provenance tracking and version control.
# =============================================================================

from .provider import TravelTimeProvider, TravelTimeResult, MatrixResult
from .static_matrix import StaticMatrixProvider, StaticMatrixConfig
from .cache import TravelTimeCache
from .matrix_generator import (
    MatrixGenerator,
    MatrixGeneratorConfig,
    GeneratedMatrix,
    MatrixValidationResult,
)
from .tt_meta import (
    TTMeta,
    StaticMatrixVersion,
    TravelTimeResultWithMeta,
    MatrixResultWithMeta,
    create_static_matrix_meta,
    create_osrm_meta,
    create_haversine_meta,
    compute_content_hash,
    compute_file_hash,
    compute_matrix_hash,
)
from .osrm_provider import (
    OSRMProvider,
    OSRMConfig,
    OSRMStatus,
    ConsecutiveTimesResult,
)

__all__ = [
    # Provider interface
    "TravelTimeProvider",
    "TravelTimeResult",
    "MatrixResult",
    # Implementations
    "StaticMatrixProvider",
    "StaticMatrixConfig",
    "TravelTimeCache",
    # OSRM Provider (V3.5)
    "OSRMProvider",
    "OSRMConfig",
    "OSRMStatus",
    "ConsecutiveTimesResult",
    # Matrix generation
    "MatrixGenerator",
    "MatrixGeneratorConfig",
    "GeneratedMatrix",
    "MatrixValidationResult",
    # Metadata and versioning (V3.5)
    "TTMeta",
    "StaticMatrixVersion",
    "TravelTimeResultWithMeta",
    "MatrixResultWithMeta",
    "create_static_matrix_meta",
    "create_osrm_meta",
    "create_haversine_meta",
    "compute_content_hash",
    "compute_file_hash",
    "compute_matrix_hash",
]
