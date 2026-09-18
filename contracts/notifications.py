from auth.email_utils import send_email

# Which ExtractedContractFields keys diff_extracted_fields() compares, and
# the human-readable label to show for each in an email.
_DIFF_FIELD_LABELS = {
    "vendor_name": "Vendor",
    "renewal_date": "Renewal Date",
    "auto_renew": "Auto-Renew",
    "cancellation_window_days": "Cancellation Window (days)",
    "pricing_amount": "Pricing Amount",
    "pricing_currency": "Pricing Currency",
    "pricing_frequency": "Billing Frequency",
}


def _safe_send(to_email: str, subject: str, plain_text_body: str, html_body: str | None = None) -> bool:
    try:
        send_email(to_email, subject, plain_text_body, html_body)
        return True
    except Exception as e:
        print(f"[notifications] failed to send '{subject}' to {to_email}: {e}")
        return False


def notify_contract_flagged(to_email: str, filename: str, flag_reason: str) -> bool:
    subject = f"VendorPulse: {filename} needs attention"
    plain = (
        f'Your contract "{filename}" has been flagged:\n\n{flag_reason}\n\n'
        "Log in to VendorPulse to review it."
    )
    html = f"<p>Your contract <b>{filename}</b> has been flagged:</p><p>{flag_reason}</p>"
    return _safe_send(to_email, subject, plain, html)


def notify_extraction_issue(to_email: str, filename: str, detail: str, failed: bool) -> bool:
    if failed:
        subject = f"VendorPulse: extraction failed for {filename}"
        plain = f'Your contract "{filename}" failed extraction:\n\n{detail}'
    else:
        subject = f"VendorPulse: check needed on {filename}"
        plain = (
            f'Your contract "{filename}" was extracted, but the model flagged '
            f"something to double-check:\n\n{detail}"
        )
    html = "<p>" + plain.replace("\n", "<br>") + "</p>"
    return _safe_send(to_email, subject, plain, html)


def notify_contract_updated(to_email: str, filename: str, diff_lines: list[str]) -> bool:
    subject = f"VendorPulse: {filename} was updated"
    if diff_lines:
        body_lines = "\n".join(f"- {line}" for line in diff_lines)
        plain = f'You replaced "{filename}" with a new version. Changes detected:\n\n{body_lines}'
    else:
        plain = (
            f'You replaced "{filename}" with a new version. No extracted-field '
            "changes were detected, but the file content was updated."
        )
    html = "<p>" + plain.replace("\n", "<br>") + "</p>"
    return _safe_send(to_email, subject, plain, html)


def diff_extracted_fields(old: dict | None, new: dict) -> list[str]:
    if not old:
        return []

    lines = []
    for field, label in _DIFF_FIELD_LABELS.items():
        old_val = old.get(field)
        new_val = new.get(field)
        if old_val != new_val:
            old_display = old_val if old_val is not None else "—"
            new_display = new_val if new_val is not None else "—"
            lines.append(f"{label}: {old_display} → {new_display}")
    return lines