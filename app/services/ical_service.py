import uuid
import re
import requests
from datetime import datetime, date
from typing import Optional

from app.models.hotel_models import Unit
from app.models.booking import Booking
from app.extensions import db

class ICalService:
    
    @staticmethod
    def generate_ical(unit_id: int) -> Optional[str]:
        """
        Generate standard .ics format string for a unit's bookings.
        """
        unit = Unit.query.get(unit_id)
        if not unit:
            return None
            
        bookings = Booking.query.filter_by(
            unit_id=unit_id,
            status='confirmed'  # only confirmed bookings block dates
        ).all()
        
        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//SaaS Hotel//NONSGML v1.0//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH"
        ]
        
        for b in bookings:
            if not b.checkin_date or not b.checkout_date:
                continue
                
            uid = f"booking-{b.id}-{uuid.uuid4()}@saashotel.com"
            dtstamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
            # For all-day events, date is YYYYMMDD
            dtstart = b.checkin_date.strftime("%Y%m%d")
            dtend = b.checkout_date.strftime("%Y%m%d")
            
            lines.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{dtstamp}",
                f"DTSTART;VALUE=DATE:{dtstart}",
                f"DTEND;VALUE=DATE:{dtend}",
                f"SUMMARY:Booking #{b.booking_number}",
                "STATUS:CONFIRMED",
                "END:VEVENT"
            ])
            
        lines.append("END:VCALENDAR")
        return "\r\n".join(lines) + "\r\n"

    @staticmethod
    def sync_unit_from_ical(unit_id: int) -> bool:
        """
        Fetch external iCal, parse it, and save to db as bookings
        to prevent double booking.
        """
        unit = Unit.query.get(unit_id)
        if not unit or not unit.ical_import_url:
            return False
            
        try:
            resp = requests.get(unit.ical_import_url, timeout=10)
            if resp.status_code != 200:
                return False
            ical_data = resp.text
        except Exception:
            return False
            
        # Very simple regex parsing for VEVENT blocks
        events = re.findall(r'BEGIN:VEVENT(.*?)END:VEVENT', ical_data, re.DOTALL)
        
        for ev in events:
            # find DTSTART
            start_m = re.search(r'DTSTART.*?:([0-9TZ]+)', ev)
            end_m = re.search(r'DTEND.*?:([0-9TZ]+)', ev)
            uid_m = re.search(r'UID:([^\r\n]+)', ev)
            
            if start_m and end_m:
                try:
                    start_str = start_m.group(1).replace('T', '').replace('Z', '')
                    end_str = end_m.group(1).replace('T', '').replace('Z', '')
                    
                    if len(start_str) >= 8:
                        checkin = datetime.strptime(start_str[:8], "%Y%m%d").date()
                    else:
                        continue
                        
                    if len(end_str) >= 8:
                        checkout = datetime.strptime(end_str[:8], "%Y%m%d").date()
                    else:
                        continue
                        
                    uid = uid_m.group(1).strip() if uid_m else str(uuid.uuid4())
                    
                    # check if this external booking already exists
                    # we use notes to store the uid to avoid duplicate
                    existing = Booking.query.filter_by(
                        unit_id=unit_id,
                        source='ical',
                        notes=f'ical_uid:{uid}'
                    ).first()
                    
                    if not existing:
                        b = Booking(
                            tenant_id=unit.tenant_id,
                            branch_id=unit.branch_id,
                            booking_type='hotel_room',
                            booking_number=Booking.generate_booking_number(),
                            customer_name='External iCal Booking',
                            checkin_date=checkin,
                            checkout_date=checkout,
                            unit_id=unit_id,
                            status='confirmed',
                            source='ical',
                            notes=f'ical_uid:{uid}'
                        )
                        db.session.add(b)
                except ValueError:
                    continue
                    
        try:
            db.session.commit()
            return True
        except Exception:
            db.session.rollback()
            return False
