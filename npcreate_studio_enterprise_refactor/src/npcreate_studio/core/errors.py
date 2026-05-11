class NPCreateError(Exception):
    """Base application error."""


class SecurityError(NPCreateError):
    """Raised when untrusted input fails safety checks."""


class ToolVerificationError(SecurityError):
    """Bundled executable/library hash is missing or invalid."""


class SubprocessBlocked(SecurityError):
    """Command was blocked because it is not in the allowlist."""


class ConfigError(NPCreateError):
    """Invalid settings/configuration."""
