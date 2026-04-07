"""SMS alert service using Fast2SMS REST API."""

import httpx
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.sms_service")

FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"


async def send_sms_alert(
    status: str,
    risk_score: float,
    temp_internal: float,
    eta_to_critical: int | None = None,
) -> bool:
    """Send an SMS alert via Fast2SMS API.

    Args:
        status: Current status (SAFE, WARNING, CRITICAL).
        risk_score: Current risk score (0-100).
        temp_internal: Current internal temperature.
        eta_to_critical: Minutes until CRITICAL, or None.

    Returns:
        True if SMS was sent successfully, False otherwise.
    """
    if settings.FAST2SMS_API_KEY == "your_key_here":
        logger.warning("Fast2SMS API key not configured — SMS alert skipped (logged only)")
        logger.info(
            f"[SMS WOULD SEND] ALERT: Vaccine storage {status}. "
            f"Risk: {risk_score}/100. Temp: {temp_internal}°C."
        )
        return False

    eta_message = ""
    if eta_to_critical is not None:
        eta_message = f"ETA to CRITICAL: {eta_to_critical} min."
    elif status == "CRITICAL":
        eta_message = "Status is CRITICAL NOW."

    message = (
        f"ALERT: Vaccine storage {status}. "
        f"Risk: {risk_score}/100. "
        f"Temp: {temp_internal}°C. "
        f"{eta_message}"
    )

    headers = {
        "authorization": settings.FAST2SMS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "route": "q",
        "message": message,
        "language": "english",
        "numbers": settings.FAST2SMS_PHONE_NUMBER,
    }

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(FAST2SMS_URL, json=payload, headers=headers)
            response.raise_for_status()
            result = response.json()
            logger.info(f"SMS sent successfully: {result}")
            return True
    except httpx.HTTPStatusError as e:
        logger.error(f"Fast2SMS API error: {e.response.status_code} — {e.response.text}")
        return False
    except httpx.RequestError as e:
        logger.error(f"Fast2SMS request failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected SMS error: {e}")
        return False
