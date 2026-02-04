import azure.functions as func
import json
import os
import logging
from openai import AzureOpenAI
import requests

# Initialize Azure OpenAI client
openai_client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    api_version="2024-05-01-preview",
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)
def main(event: func.EventHubEvent):
    try:
        # Parse batch of logs from Event Hub
        raw_logs = json.loads(event.get_body().decode('utf-8'))
        # Filter: Only ERROR, WARNING, CRITICAL
        high_sev_logs = [
            log for log in raw_logs
            if log.get("Level") in ["Error", "Warning", "Critical", "err", "warn"]
        ]
        if not high_sev_logs:
            logging.info("No high-severity logs. Skipping AI analysis.")
            return
        # Limit to last 15 logs to control token usage
        recent_logs = high_sev_logs[-15:]
        # Build prompt for Azure OpenAI
        prompt = f"""
You are an expert Azure DevOps engineer. Analyze these logs and return ONLY a JSON object with:
- "has_issue": true/false
- "summary": one-sentence plain-English description
- "severity": "low" | "medium" | "high" | "critical"
- "suggested_actions": array of 1-2 specific remediation steps
Logs:
{json.dumps(recent_logs, indent=2)}
        """
        # Call Azure OpenAI
        response = openai_client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME"),  # e.g., "gpt-4o"
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            max_tokens=500,
            temperature=0.0
        )
        insight = json.loads(response.choices[0].message.content)
        # Send alert if issue detected
        if insight.get("has_issue", False):
            send_teams_alert(insight)
            logging.info(f"AI Alert Sent: {insight['summary']}")
        # Optional: Log AI decisions back to Log Analytics via custom log
        log_ai_decision(insight)
    except Exception as e:
        logging.error(f"AI Agent Error: {str(e)}")
        # Consider sending to Dead Letter Queue or PagerDuty
def send_teams_alert(insight: dict):
    webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
    color = {
        "critical": "FF0000",
        "high": "FF6347",
        "medium": "FFA500",
        "low": "90EE90"
    }.get(insight.get("severity", "medium"), "808080")
    card = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "themeColor": color,
        "summary": "AI Log Monitor Alert",
        "sections": [{
            "activityTitle": "🤖 AI Log Monitoring Agent Alert",
            "facts": [
                {"name": "Summary", "value": insight.get("summary", "N/A")},
                {"name": "Severity", "value": insight.get("severity", "unknown").title()},
                {"name": "Suggested Actions", "value": "\n".join(insight.get("suggested_actions", []))}
            ],
            "markdown": True
        }],
        "potentialAction": [{
            "@type": "OpenUri",
            "name": "View Logs in Azure Portal",
            "targets": [{"os": "default", "uri": "https://portal.azure.com/#blade/Microsoft_Azure_Monitoring_Logs/LogsBlade"}]
        }]
    }
    requests.post(webhook_url, json=card, timeout=10)
def log_ai_decision(insight: dict):
    # Optional: Send structured log to Application Insights or Log Analytics
    # For simplicity, we log to Function's built-in logging (appears in Monitor tab)
    logging.info(f"AI_DECISION: {json.dumps(insight)}")