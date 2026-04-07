"""REST API endpoints and WebSocket handler."""

import os
from datetime import datetime
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from models.schemas import SensorDataInput, ProcessedReading, SimulateTriggerRequest
from processing.pipeline import process_reading
from database.crud import (
    get_readings, get_latest_reading, get_incidents,
    get_latest_incident, get_incident_by_id, insert_reading
)
from api.websocket_manager import ws_manager
from triggers.trigger_engine import trigger_engine
from config.settings import settings
from utils.logger import setup_logger

logger = setup_logger("vaccine_monitor.routes")

router = APIRouter()


@router.get("/health")
async def health_check():
    """Health check endpoint.

    Returns:
        JSON with status and current mode.
    """
    return {
        "status": "ok",
        "mode": "simulation" if settings.SIMULATION_MODE else "live",
        "websocket_connections": ws_manager.connection_count,
    }


@router.get("/api/readings")
async def api_get_readings(limit: int = Query(default=60, ge=1, le=500)):
    """Get the last N sensor readings.

    Args:
        limit: Maximum number of readings (default 60, max 500).

    Returns:
        JSON array of reading objects.
    """
    readings = await get_readings(limit=limit)
    return readings


@router.get("/api/readings/latest")
async def api_get_latest_reading():
    """Get the single most recent sensor reading.

    Returns:
        JSON reading object or 404.
    """
    reading = await get_latest_reading()
    if reading is None:
        return JSONResponse(
            status_code=404,
            content={"detail": "No readings available yet"}
        )
    return reading


@router.get("/api/status")
async def api_get_status():
    """Get current system status summary.

    Returns:
        JSON with risk score, status, ETA, VVM damage.
    """
    reading = await get_latest_reading()
    if reading is None:
        return {
            "risk_score": 0,
            "status": "SAFE",
            "eta_to_critical": None,
            "vvm_damage": 0,
            "potency_percent": 100.0,
            "exposure_minutes": 0,
            "temp_internal": 0,
            "timestamp": datetime.utcnow().isoformat(),
        }
    return {
        "risk_score": reading["risk_score"],
        "status": reading["status"],
        "eta_to_critical": reading["eta_to_critical"],
        "vvm_damage": reading["vvm_damage"],
        "potency_percent": reading["potency_percent"],
        "exposure_minutes": reading["exposure_minutes"],
        "temp_internal": reading["temp_internal"],
        "timestamp": reading["timestamp"],
    }


@router.get("/api/incidents")
async def api_get_incidents():
    """Get all incident records.

    Returns:
        JSON array of incident objects.
    """
    incidents = await get_incidents()
    return incidents


@router.get("/api/report/latest")
async def api_get_latest_report():
    """Get the latest Claude-generated incident report text.

    Returns:
        JSON with report text.
    """
    # First check trigger engine for in-memory report
    if trigger_engine.latest_report:
        return {"report": trigger_engine.latest_report}

    # Fall back to database
    incident = await get_latest_incident()
    if incident and incident.get("report_text"):
        return {"report": incident["report_text"]}

    return {"report": "No incident reports generated yet. The system will generate a report when a status change is detected."}


@router.get("/api/pdf/{incident_id}")
async def api_download_pdf(incident_id: int):
    """Download a vaccine passport PDF by incident ID.

    Args:
        incident_id: The incident ID.

    Returns:
        PDF file download or 404.
    """
    incident = await get_incident_by_id(incident_id)
    if incident is None:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Incident {incident_id} not found"}
        )

    pdf_path = incident.get("pdf_path")
    if pdf_path is None or not os.path.exists(pdf_path):
        return JSONResponse(
            status_code=404,
            content={"detail": f"PDF not available for incident {incident_id}"}
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"vaccine_passport_{incident_id}.pdf",
    )


@router.post("/api/simulate/trigger")
async def api_simulate_trigger(request: SimulateTriggerRequest = None):
    """Manually trigger a simulated reading for demo purposes.

    Args:
        request: Optional custom sensor values.

    Returns:
        JSON with processed reading data.
    """
    if request is None:
        request = SimulateTriggerRequest()

    sensor_data = SensorDataInput(
        temp_internal=request.temp_internal,
        temp_external=request.temp_external,
        humidity=request.humidity,
        timestamp=datetime.utcnow().isoformat(),
    )

    try:
        # Process the reading
        processed = await process_reading(sensor_data)

        # Write to database
        await insert_reading(
            timestamp=processed.timestamp,
            temp_internal=processed.temp_internal,
            temp_external=processed.temp_external,
            humidity=processed.humidity,
            risk_score=processed.risk_score,
            status=processed.status,
            vvm_damage=processed.vvm_damage,
            exposure_minutes=processed.exposure_minutes,
            is_anomaly=processed.is_anomaly,
            potency_percent=processed.potency_percent,
            eta_to_critical=processed.eta_to_critical,
        )

        # Evaluate triggers
        await trigger_engine.evaluate(processed)

        # Broadcast via WebSocket
        await ws_manager.broadcast(processed.model_dump())

        logger.info(f"Manual trigger processed: status={processed.status}")
        return processed.model_dump()

    except Exception as e:
        logger.error(f"Manual trigger failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": str(e)}
        )
