"""Raw crawl -> provider labeling -> review proposals API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from core.contracts.ai_pipeline import RawCrawlRecord
from api.deps import get_db_session
from providers.google_genai import ProviderConfigurationError, ProviderResponseError
from services.ai_ingestion import ingest_and_label_records

router = APIRouter(prefix="/api/ingest", tags=["ingest"])


class IngestLabelPayload(BaseModel):
    provider_id: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    crawler_name: str = Field(default="manual-ai-smoke", min_length=1)
    schema_type: str = Field(default="product_offer", min_length=1)
    records: list[RawCrawlRecord] = Field(min_length=1, max_length=30)


@router.post("/raw-records/label", status_code=status.HTTP_200_OK)
def label_raw_records(
    payload: IngestLabelPayload,
    session: Session = Depends(get_db_session),
) -> dict:
    try:
        return ingest_and_label_records(
            session=session,
            provider_id=payload.provider_id,
            source_name=payload.source_name,
            crawler_name=payload.crawler_name,
            schema_type=payload.schema_type,
            records=payload.records,
        )
    except ProviderConfigurationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ProviderResponseError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=exc.to_detail(),
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
