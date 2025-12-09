#!/usr/bin/env python3
"""
Send daily DartsAtlas results to regional directors via email.

Environment variables required:
  SMTP_SERVER   - e.g., smtp.gmail.com
  SMTP_PORT     - e.g., 587
  SMTP_USERNAME - your email address
  SMTP_PASSWORD - your email password or app-specific password
  EMAIL_FROM    - sender address
  EMAIL_TO      - comma-separated list of recipient addresses
"""

import os
import sys
import smtplib
import datetime as dt
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

# Regional directors mapping (for personalised emails if needed)
REGIONAL_DIRECTORS = {
    "Scotland": "Claire Louise",
    "Wales": "Hywel Llewellyn",
    "Ireland": "John O'Toole",
    "Northern Ireland": "James Mulvaney",
    "North East": "Andrew Fletcher",
    "Yorkshire & Humber": "Adam Mould",
    "North West": "Paul Hale",
    "Midlands": "Karl Coleman",
    "South West": "Simon Rimington",
    "South East & London": "TBC",
    "East of England": "TBC",
}


def get_env(key: str, default: str = None) -> str:
    """Get environment variable or raise error if required and missing."""
    value = os.environ.get(key, default)
    if value is None:
        print(f"ERROR: Missing required environment variable: {key}")
        sys.exit(1)
    return value


def find_result_files(output_dir: str = "output") -> tuple[list[Path], Path | None]:
    """Find social text files and CSV in the output directory."""
    output_path = Path(output_dir)
    
    if not output_path.exists():
        print(f"ERROR: Output directory '{output_dir}' does not exist")
        return [], None
    
    # Find all social_*.txt files
    social_files = sorted(output_path.glob("social_*.txt"))
    
    # Find the CSV file
    csv_files = list(output_path.glob("dartsatlas_results_*.csv"))
    csv_file = csv_files[0] if csv_files else None
    
    return social_files, csv_file


def create_email_body(social_files: list[Path], csv_file: Path | None) -> str:
    """Create the email body with a summary of results."""
    today = dt.date.today()
    
    body = f"""ADC Daily Results - {today.strftime('%A %d %B %Y')}

Hi Team,

Please find attached the tournament results from yesterday's events.

"""
    
    if social_files:
        body += f"Results files attached: {len(social_files)} region(s)\n\n"
        
        # List regions with results
        regions_with_results = []
        for f in social_files:
            # Extract region from filename like "social_Scotland_2025-01-15.txt"
            name = f.stem  # social_Scotland_2025-01-15
            parts = name.replace("social_", "").rsplit("_", 1)
            if parts:
                region = parts[0].replace("_", " ")
                regions_with_results.append(region)
        
        if regions_with_results:
            body += "Regions with events:\n"
            for region in sorted(regions_with_results):
                director = REGIONAL_DIRECTORS.get(region, "")
                if director and director != "TBC":
                    body += f"  • {region} ({director})\n"
                else:
                    body += f"  • {region}\n"
            body += "\n"
    else:
        body += "No tournament results found for yesterday.\n\n"
    
    if csv_file:
        body += f"Full data export: {csv_file.name}\n\n"
    
    body += """Best regards,
ADC Automated Results System

---
This is an automated email from the Amateur Darts Circuit results system.
"""
    
    return body


def send_email(
    smtp_server: str,
    smtp_port: int,
    username: str,
    password: str,
    from_addr: str,
    to_addrs: list[str],
    subject: str,
    body: str,
    attachments: list[Path]
) -> bool:
    """Send email with attachments."""
    
    # Create message
    msg = MIMEMultipart()
    msg['From'] = from_addr
    msg['To'] = ", ".join(to_addrs)
    msg['Subject'] = subject
    
    # Attach body
    msg.attach(MIMEText(body, 'plain'))
    
    # Attach files
    for filepath in attachments:
        if not filepath.exists():
            print(f"WARNING: Attachment not found: {filepath}")
            continue
            
        try:
            with open(filepath, 'rb') as f:
                part = MIMEBase('application', 'octet-stream')
                part.set_payload(f.read())
            
            encoders.encode_base64(part)
            part.add_header(
                'Content-Disposition',
                f'attachment; filename="{filepath.name}"'
            )
            msg.attach(part)
            print(f"Attached: {filepath.name}")
        except Exception as e:
            print(f"WARNING: Failed to attach {filepath}: {e}")
    
    # Send email
    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(username, password)
            server.send_message(msg)
        print(f"Email sent successfully to {len(to_addrs)} recipient(s)")
        return True
    except Exception as e:
        print(f"ERROR: Failed to send email: {e}")
        return False


def main():
    """Main entry point."""
    print("=" * 50)
    print("ADC Daily Results Email Sender")
    print("=" * 50)
    
    # Get configuration from environment
    smtp_server = get_env("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(get_env("SMTP_PORT", "587"))
    username = get_env("SMTP_USERNAME")
    password = get_env("SMTP_PASSWORD")
    from_addr = get_env("EMAIL_FROM")
    to_addrs = [addr.strip() for addr in get_env("EMAIL_TO").split(",")]
    
    print(f"SMTP Server: {smtp_server}:{smtp_port}")
    print(f"From: {from_addr}")
    print(f"To: {', '.join(to_addrs)}")
    print()
    
    # Find result files
    social_files, csv_file = find_result_files("output")
    
    print(f"Found {len(social_files)} social text file(s)")
    if csv_file:
        print(f"Found CSV: {csv_file.name}")
    print()
    
    # Prepare attachments
    attachments = list(social_files)
    if csv_file:
        attachments.append(csv_file)
    
    if not attachments:
        print("No result files found - sending notification email anyway")
    
    # Create email
    today = dt.date.today()
    subject = f"ADC Daily Results - {today.strftime('%d %B %Y')}"
    body = create_email_body(social_files, csv_file)
    
    # Send email
    success = send_email(
        smtp_server=smtp_server,
        smtp_port=smtp_port,
        username=username,
        password=password,
        from_addr=from_addr,
        to_addrs=to_addrs,
        subject=subject,
        body=body,
        attachments=attachments
    )
    
    if not success:
        sys.exit(1)
    
    print("\nDone!")


if __name__ == "__main__":
    main()
