"""
Email digest generator and sender.

Queries the database for the highest-scoring analyzed items,
generates a clean HTML email, and sends it via Resend.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone, timedelta

import resend
import structlog

from src.storage.postgres_client import PostgresClient

logger = structlog.get_logger()


class DigestGenerator:
    """
    Generates and sends the AI Intelligence Digest email.

    Usage:
        generator = DigestGenerator(db, resend_api_key, from_email, to_emails)
        result = await generator.generate_and_send(period_days=1)
    """

    def __init__(
        self,
        db: PostgresClient,
        resend_api_key: str,
        from_email: str,
        to_emails: list[str],
    ):
        self.db = db
        self.from_email = from_email
        self.to_emails = to_emails
        resend.api_key = resend_api_key

    async def generate_and_send(
        self,
        period_days: int = 1,
        top_n: int = 10,
        dry_run: bool = False,
    ) -> dict:
        """
        Generate the digest and optionally send it.

        Returns dict with report details.
        """
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=period_days)

        # Fetch top signals
        items = await self.db.get_top_signals(since=since, until=now, limit=50)

        if not items:
            logger.info("digest.no_items", period_days=period_days)
            return {"status": "no_items", "count": 0}

        # Sort by relevance score descending, take top N
        items.sort(key=lambda x: (x.relevance_score or 0, x.engagement_score or 0), reverse=True)
        top_items = items[:top_n]

        # Count totals
        total_items = await self.db.get_item_count()

        # Build the email
        subject = f"Sifter AI Digest — {now.strftime('%b %d, %Y')}"
        html = self._build_html(top_items, since, now, len(items), total_items)

        result = {
            "status": "generated",
            "subject": subject,
            "signals_count": len(top_items),
            "total_candidates": len(items),
            "period": f"{since.strftime('%b %d')} - {now.strftime('%b %d, %Y')}",
        }

        if dry_run:
            result["html"] = html
            result["status"] = "dry_run"
            return result

        # Send via Resend
        try:
            send_result = resend.Emails.send({
                "from": self.from_email,
                "to": self.to_emails,
                "subject": subject,
                "html": html,
            })
            result["status"] = "sent"
            result["resend_id"] = send_result.get("id", "")
            logger.info("digest.sent", to=self.to_emails, signals=len(top_items))

            # Log to database
            await self.db.insert_digest(
                period_start=since,
                period_end=now,
                signal_ids=[item.id for item in top_items],
                total_items=len(items),
                report_html=html,
            )

        except Exception as e:
            result["status"] = "send_failed"
            result["error"] = str(e)
            logger.error("digest.send_failed", error=str(e))

        return result

    def _build_html(
        self,
        items: list,
        since: datetime,
        until: datetime,
        total_candidates: int,
        total_db_items: int,
    ) -> str:
        """Build the digest HTML email — matches Sifter AI landing page design."""

        sentiment_colors = {
            "positive": "#15803d",
            "negative": "#dc2626",
            "neutral": "#737373",
            "mixed": "#d97706",
        }

        signal_labels = {
            "product_launch": "Product",
            "funding_round": "Funding",
            "research_breakthrough": "Research",
            "tool_release": "Tool",
            "trend_shift": "Trend",
            "opinion_analysis": "Opinion",
            "tutorial": "Tutorial",
            "hiring_signal": "Hiring",
            "partnership": "Partnership",
            "regulatory": "Regulation",
            "acquisition": "Acquisition",
            "open_source": "Open Source",
            "benchmark": "Benchmark",
            "other": "Other",
        }

        # Build signal blocks
        signal_blocks = ""
        for i, item in enumerate(items, 1):
            dot_color = sentiment_colors.get(item.sentiment or "neutral", "#737373")
            label = signal_labels.get(item.signal_type or "other", "Other")
            title = item.title or item.summary or "Untitled"
            summary = item.summary or ""
            source = (item.source_platform or "unknown").capitalize()
            if source == "Hackernews":
                source = "Hacker News"
            score = item.relevance_score or 0
            url = item.source_url or "#"
            rank = f"{i:02d}"

            signal_blocks += f"""
            <tr>
              <td style="padding: 0;">
                <table width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td style="padding: 20px 32px; border-bottom: 1px solid #e7e5e4;">
                      <!-- Meta row -->
                      <table cellpadding="0" cellspacing="0" style="margin-bottom: 8px;">
                        <tr>
                          <td style="font-family: Georgia, 'Times New Roman', serif; font-size: 14px; color: #a8a29e; padding-right: 10px; vertical-align: middle;">{rank}</td>
                          <td style="width: 7px; height: 7px; vertical-align: middle; padding-right: 10px;"><div style="width: 7px; height: 7px; border-radius: 50%; background: {dot_color};"></div></td>
                          <td style="vertical-align: middle; padding-right: 10px;"><span style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: #57534e; background: #f5f5f4; padding: 3px 8px; border-radius: 3px;">{label}</span></td>
                          <td style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 11px; color: #a8a29e; vertical-align: middle;">{source} &middot; {score}/10</td>
                        </tr>
                      </table>
                      <!-- Title -->
                      <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 15px; font-weight: 600; color: #0f1114; line-height: 1.4; margin-bottom: 6px;">
                        <a href="{url}" style="color: #0f1114; text-decoration: none;">{title[:100]}</a>
                      </div>
                      <!-- Summary -->
                      <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; color: #57534e; line-height: 1.55;">
                        {summary}
                      </div>
                      <!-- Link -->
                      <div style="margin-top: 8px;">
                        <a href="{url}" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 12px; color: #1d4ed8; text-decoration: none; font-weight: 500;">Read source &#8594;</a>
                      </div>
                    </td>
                  </tr>
                </table>
              </td>
            </tr>"""

        # Full email HTML
        html = f"""
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!--[if mso]><style>table, td {{font-family: Arial, sans-serif !important;}}</style><![endif]-->
</head>
<body style="margin: 0; padding: 0; background-color: #fafaf9; -webkit-font-smoothing: antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background-color: #fafaf9; padding: 24px 0;">
    <tr>
      <td align="center">
        <table width="600" cellpadding="0" cellspacing="0" style="background-color: #ffffff; border: 1px solid #e7e5e4; border-radius: 4px; overflow: hidden;">

          <!-- Header -->
          <tr>
            <td style="padding: 32px 32px 24px 32px; border-bottom: 1px solid #e7e5e4;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td>
                    <div style="font-family: Georgia, 'Times New Roman', serif; font-size: 22px; color: #0f1114; letter-spacing: -0.5px;">Sifter AI</div>
                  </td>
                  <td align="right">
                    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 12px; color: #a8a29e;">{until.strftime('%B %d, %Y')}</div>
                  </td>
                </tr>
              </table>
              <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 13px; color: #78716c; margin-top: 8px;">
                {len(items)} signals from {total_candidates} items analyzed this period
              </div>
            </td>
          </tr>

          <!-- Signals -->
          {signal_blocks}

          <!-- Footer -->
          <tr>
            <td style="padding: 24px 32px; background-color: #fafaf9; border-top: 1px solid #e7e5e4;">
              <table width="100%" cellpadding="0" cellspacing="0">
                <tr>
                  <td style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 12px; color: #a8a29e; line-height: 1.6;">
                    <div>Sifter AI &middot; AI intelligence, distilled.</div>
                    <div style="margin-top: 4px;">Sources: Hacker News &middot; ArXiv &middot; TechCrunch &middot; Google AI &middot; Latent Space &middot; +15 more</div>
                  </td>
                </tr>
                <tr>
                  <td style="padding-top: 12px;">
                    <a href="#" style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; font-size: 11px; color: #a8a29e; text-decoration: underline;">Unsubscribe</a>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
      </td>
    </tr>
  </table>
</body>
</html>"""

        return html