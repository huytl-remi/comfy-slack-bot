class SDSlackBotError(Exception):
    """Base exception class for SD Slack Bot"""

class ConfigurationError(SDSlackBotError):
    """Raised when there's an issue with the configuration"""

class ImageGenerationError(SDSlackBotError):
    """Raised when there's an error during image generation"""

class SlackAPIError(SDSlackBotError):
    """Raised when there's an error interacting with the Slack API"""

class QueueError(SDSlackBotError):
    """Raised when there's an issue with the request queue"""
