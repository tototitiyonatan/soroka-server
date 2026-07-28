from fastapi import FastAPI, Depends, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import create_engine, Column, Integer, String, Date, ForeignKey, Text
from sqlalchemy.orm import declarative_base, sessionmaker, Session, relationship
from pydantic import BaseModel, field_validator, ConfigDict, ValidationInfo, Field
from typing import List, Optional
from datetime import date
import pandas as pd
import io
import os


# ----------------- 1. הגדרת בסיס הנתונים (SQLAlchemy) -----------------
SQLALCHEMY_DATABASE_URL = "sqlite:///./soroka_staff.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Staff(Base):
    __tablename__ = "staff"
    id = Column(String, primary_key=True, index=True)  # ת.ז כמזהה
    first_name = Column(String, nullable=False)
    last_name = Column(String, nullable=False)
    role = Column(String, nullable=False)  # מנהל, מומחה, מתמחה
    phone = Column(String)
    email = Column(String)

    absences = relationship("Absence", back_populates="staff")
    schedules = relationship("Schedule", back_populates="staff")


class Station(Base):
    __tablename__ = "stations"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    parent_station_id = Column(Integer, ForeignKey("stations.id"), nullable=True)  # תמיכה בתת-תחנות

    schedules = relationship("Schedule", back_populates="station")


class Absence(Base):
    __tablename__ = "absences"
    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(String, ForeignKey("staff.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status_type = Column(String, nullable=False)  # חופשה, מחלה, אחרי תורנות וכו'
    notes = Column(Text, nullable=True)

    staff = relationship("Staff", back_populates="absences")


class Schedule(Base):
    __tablename__ = "schedules"
    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(String, ForeignKey("staff.id"), nullable=False)
    date = Column(Date, nullable=False)
    station_id = Column(Integer, ForeignKey("stations.id"), nullable=False)

    staff = relationship("Staff", back_populates="schedules")
    station = relationship("Station", back_populates="schedules")


class LeaveRequest(Base):
    __tablename__ = "leave_requests"
    id = Column(Integer, primary_key=True, index=True)
    staff_id = Column(String, ForeignKey("staff.id"), nullable=False)
    start_date = Column(Date, nullable=False)
    end_date = Column(Date, nullable=False)
    status_type = Column(String, nullable=False)
    notes = Column(Text, nullable=True)
    status = Column(String, default="ממתין לאישור")

    staff = relationship("Staff")


Base.metadata.create_all(bind=engine)


# ----------------- 2. הגדרת סכימות (Pydantic V2) -----------------
class StaffBase(BaseModel):
    id: str
    first_name: str
    last_name: str
    role: str
    phone: Optional[str] = None
    email: Optional[str] = None


class StaffCreate(StaffBase):
    pass

class StaffUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    role: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None


class StaffResponse(StaffBase):
    model_config = ConfigDict(from_attributes=True)


class AbsenceBase(BaseModel):
    staff_id: str
    start_date: date
    end_date: date
    status_type: str
    notes: Optional[str] = None


class AbsenceCreate(AbsenceBase):
    @field_validator('end_date')
    @classmethod
    def check_dates(cls, v, info: ValidationInfo):
        if 'start_date' in info.data and v < info.data['start_date']:
            raise ValueError('תאריך הסיום חייב להיות שווה או מאוחר לתאריך ההתחלה')
        return v


class AbsenceResponse(AbsenceBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class StationBase(BaseModel):
    name: str
    parent_station_id: Optional[int] = None


class StationCreate(StationBase):
    pass


class StationResponse(StationBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class ScheduleBase(BaseModel):
    staff_id: str
    date: date
    station_id: int


class ScheduleCreate(ScheduleBase):
    pass


class ScheduleResponse(ScheduleBase):
    id: int
    model_config = ConfigDict(from_attributes=True)


class LeaveRequestBase(BaseModel):
    staff_id: str
    start_date: date
    end_date: date
    status_type: str
    notes: Optional[str] = None


class LeaveRequestCreate(LeaveRequestBase):
    pass


class LeaveRequestResponse(LeaveRequestBase):
    id: int
    status: str
    model_config = ConfigDict(from_attributes=True)


class DashboardStats(BaseModel):
    date: date
    total_staff: int
    present: int
    present_breakdown: dict = Field(description="חלוקה לפי תפקיד")
    absent: int
    absent_breakdown: dict = Field(description="חלוקה לפי סיבת היעדרות ותפקיד")


# ----------------- 3. אתחול FastAPI והגדרת CORS -----------------
app = FastAPI(title="Soroka Women's Division Staff Management")

origins = [
    "https://my-app-psi-gold-76.vercel.app",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Global exception handler (add here) ---
from fastapi.responses import JSONResponse

@app.exception_handler(Exception)
async def unhandled_exception_handler(request, exc):
    response = JSONResponse(status_code=500, content={"detail": str(exc)})
    origin = request.headers.get("origin")
    if origin in origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


# --- פונקציית עזר למסד הנתונים ---
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/")
def read_root():
    return {"message": "מערכת ניהול צוות סורוקה פועלת בהצלחה!"}


# --- פעולות צוות (Staff) ---
@app.post("/staff/", response_model=StaffResponse)
def create_staff(staff: StaffCreate, db: Session = Depends(get_db)):
    if db.query(Staff).filter(Staff.id == staff.id).first():
        raise HTTPException(status_code=400, detail="איש צוות קיים")
    new_staff = Staff(**staff.model_dump())
    db.add(new_staff)
    db.commit()
    db.refresh(new_staff)
    return new_staff

@app.post("/staff/upload")
async def upload_staff_file(file: UploadFile = File(...), db: Session = Depends(get_db)):
    if not file.filename.endswith('.csv'):
        raise HTTPException(status_code=400, detail="File must be a CSV")

    contents = await file.read()
    df = pd.read_csv(io.StringIO(contents.decode('utf-8')), dtype=str)  # force everything to str
    df = df.where(pd.notnull(df), None)  # convert NaN -> None

    added_count = 0
    skipped_count = 0
    errors = []

    for idx, row in df.iterrows():
        try:
            staff_data = StaffCreate(**row.to_dict())
        except Exception as e:
            errors.append({"row": idx, "error": str(e)})
            continue

        if not db.query(Staff).filter(Staff.id == staff_data.id).first():
            new_staff = Staff(**staff_data.model_dump())
            db.add(new_staff)
            added_count += 1
        else:
            skipped_count += 1

    db.commit()
    return {
        "message": f"Added {added_count} new staff members. Skipped {skipped_count} existing members.",
        "errors": errors
    }

@app.put("/staff/{staff_id}", response_model=StaffResponse)
def update_staff(staff_id: str, staff_update: StaffUpdate, db: Session = Depends(get_db)):
    staff_member = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff_member:
        raise HTTPException(status_code=404, detail="איש הצוות לא נמצא")

    update_data = staff_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(staff_member, key, value)
    
    db.commit()
    db.refresh(staff_member)
    return staff_member


@app.get("/staff/", response_model=List[StaffResponse])
def get_all_staff(db: Session = Depends(get_db)):
    return db.query(Staff).all()


@app.delete("/staff/{staff_id}")
def delete_staff(staff_id: str, db: Session = Depends(get_db)):
    staff_member = db.query(Staff).filter(Staff.id == staff_id).first()
    if not staff_member:
        raise HTTPException(status_code=404, detail="איש הצוות לא נמצא")

    db.query(Absence).filter(Absence.staff_id == staff_id).delete()
    db.query(Schedule).filter(Schedule.staff_id == staff_id).delete()
    db.query(LeaveRequest).filter(LeaveRequest.staff_id == staff_id).delete()

    db.delete(staff_member)
    db.commit()
    return {"message": "איש הצוות נמחק בהצלחה"}


# --- פעולות היעדרויות (Absences) ---
@app.post("/absences/", response_model=AbsenceResponse)
def create_absence(absence: AbsenceCreate, db: Session = Depends(get_db)):
    if not db.query(Staff).filter(Staff.id == absence.staff_id).first():
        raise HTTPException(status_code=404, detail="איש צוות לא נמצא")
    new_absence = Absence(**absence.model_dump())
    db.add(new_absence)
    db.commit()
    db.refresh(new_absence)
    return new_absence


@app.get("/absences/", response_model=List[AbsenceResponse])
def get_all_absences(db: Session = Depends(get_db)):
    return db.query(Absence).all()


@app.delete("/absences/{absence_id}")
def delete_absence(absence_id: int, db: Session = Depends(get_db)):
    absence = db.query(Absence).filter(Absence.id == absence_id).first()
    if not absence:
        raise HTTPException(status_code=404, detail="ההיעדרות לא נמצאה")

    db.delete(absence)
    db.commit()
    return {"message": "ההיעדרות נמחקה בהצלחה"}


# --- פעולות תחנות (Stations) ---
@app.post("/stations/", response_model=StationResponse)
def create_station(station: StationCreate, db: Session = Depends(get_db)):
    new_station = Station(**station.model_dump())
    db.add(new_station)
    db.commit()
    db.refresh(new_station)
    return new_station


@app.get("/stations/", response_model=List[StationResponse])
def get_all_stations(db: Session = Depends(get_db)):
    return db.query(Station).all()


# --- פעולות שיבוצים (Schedules) ---
@app.post("/schedules/", response_model=ScheduleResponse)
def create_schedule(schedule: ScheduleCreate, db: Session = Depends(get_db)):
    if not db.query(Staff).filter(Staff.id == schedule.staff_id).first():
        raise HTTPException(status_code=404, detail="איש הצוות לא נמצא")
    if not db.query(Station).filter(Station.id == schedule.station_id).first():
        raise HTTPException(status_code=404, detail="התחנה לא נמצאה")

    # בדיקת התנגשות עם היעדרויות
    overlapping_absence = db.query(Absence).filter(
        Absence.staff_id == schedule.staff_id,
        Absence.start_date <= schedule.date,
        Absence.end_date >= schedule.date
    ).first()

    if overlapping_absence:
        raise HTTPException(
            status_code=400,
            detail=f"שגיאת שיבוץ: איש הצוות מוגדר כנעדר בתאריך זה עקב {overlapping_absence.status_type}"
        )

    # מניעת כפילות באותו יום
    existing_schedule = db.query(Schedule).filter(
        Schedule.staff_id == schedule.staff_id,
        Schedule.date == schedule.date
    ).first()
    if existing_schedule:
        raise HTTPException(status_code=400, detail="איש הצוות כבר משובץ לתחנה ביום זה")

    new_schedule = Schedule(**schedule.model_dump())
    db.add(new_schedule)
    db.commit()
    db.refresh(new_schedule)
    return new_schedule


@app.get("/schedules/", response_model=List[ScheduleResponse])
def get_all_schedules(db: Session = Depends(get_db)):
    return db.query(Schedule).all()


@app.delete("/schedules/{schedule_id}")
def delete_schedule(schedule_id: int, db: Session = Depends(get_db)):
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="השיבוץ לא נמצא")

    try:
        db.delete(schedule)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"שגיאה במחיקת השיבוץ: {str(e)}")

    return {"message": "השיבוץ נמחק בהצלחה"}


# --- פעולות בקשות חופשה (Leave Requests) ---
@app.post("/leave-requests/", response_model=LeaveRequestResponse)
def create_leave_request(req: LeaveRequestCreate, db: Session = Depends(get_db)):
    if not db.query(Staff).filter(Staff.id == req.staff_id).first():
        raise HTTPException(status_code=404, detail="איש צוות לא נמצא")
    new_req = LeaveRequest(**req.model_dump(), status="ממתין לאישור")
    db.add(new_req)
    db.commit()
    db.refresh(new_req)
    return new_req


@app.get("/leave-requests/", response_model=List[LeaveRequestResponse])
def get_all_leave_requests(db: Session = Depends(get_db)):
    return db.query(LeaveRequest).all()


@app.put("/leave-requests/{req_id}")
def update_leave_request_status(req_id: int, action: str, db: Session = Depends(get_db)):
    leave_req = db.query(LeaveRequest).filter(LeaveRequest.id == req_id).first()
    if not leave_req:
        raise HTTPException(status_code=404, detail="בקשה לא נמצאה")

    if action == 'approve':
        leave_req.status = "אושר"
        new_absence = Absence(
            staff_id=leave_req.staff_id,
            start_date=leave_req.start_date,
            end_date=leave_req.end_date,
            status_type=leave_req.status_type,
            notes=f"אושר מתוך בקשת צוות. {leave_req.notes or ''}"
        )
        db.add(new_absence)
    elif action == 'reject':
        leave_req.status = "נדחה"
    else:
        raise HTTPException(status_code=400, detail="פעולה לא חוקית")

    db.commit()
    return {"message": f"הבקשה טופלה בהצלחה: {leave_req.status}"}


# --- דאשבורד (Dashboard Stats) ---
@app.get("/dashboard/stats", response_model=DashboardStats)
def get_dashboard_stats(target_date: date, db: Session = Depends(get_db)):
    all_staff = db.query(Staff).all()
    total_staff_count = len(all_staff)

    active_absences = db.query(Absence).filter(
        Absence.start_date <= target_date,
        Absence.end_date >= target_date
    ).all()

    absent_staff_ids = {absence.staff_id: absence.status_type for absence in active_absences}
    absent_count = len(absent_staff_ids)

    present_breakdown = {"מנהל": 0, "מומחה": 0, "מתמחה": 0}
    absent_breakdown = {}

    for person in all_staff:
        role = person.role
        if person.id not in absent_staff_ids:
            if role in present_breakdown:
                present_breakdown[role] += 1
            else:
                present_breakdown[role] = 1
        else:
            status = absent_staff_ids[person.id]
            if status not in absent_breakdown:
                absent_breakdown[status] = {"total": 0, "breakdown": {"מנהל": 0, "מומחה": 0, "מתמחה": 0}}
            absent_breakdown[status]["total"] += 1
            if role in absent_breakdown[status]["breakdown"]:
                absent_breakdown[status]["breakdown"][role] += 1
            else:
                absent_breakdown[status]["breakdown"][role] = 1

    present_count = total_staff_count - absent_count

    return {
        "date": target_date,
        "total_staff": total_staff_count,
        "present": present_count,
        "present_breakdown": present_breakdown,
        "absent": absent_count,
        "absent_breakdown": absent_breakdown
    }


# --- ייצוא לאקסל ---
@app.get("/schedules/export/excel")
def export_schedules_excel(start_date: date, end_date: date, db: Session = Depends(get_db)):
    schedules = db.query(Schedule, Staff, Station).join(
        Staff, Schedule.staff_id == Staff.id
    ).join(
        Station, Schedule.station_id == Station.id
    ).filter(
        Schedule.date >= start_date,
        Schedule.date <= end_date
    ).all()

    if not schedules:
        raise HTTPException(status_code=404, detail="לא נמצאו שיבוצים בטווח התאריכים המבוקש")

    data = []
    for sched, staff, station in schedules:
        data.append({
            "תאריך": sched.date.strftime("%d/%m/%Y"),
            "תעודת זהות": staff.id,
            "שם פרטי": staff.first_name,
            "שם משפחה": staff.last_name,
            "תפקיד": staff.role,
            "תחנה": station.name
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='סידור עבודה')
    output.seek(0)

    headers = {
        'Content-Disposition': f'attachment; filename="Schedules_{start_date}_to_{end_date}.xlsx"'
    }
    return StreamingResponse(
        output,
        headers=headers,
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("main:app", host="0.0.0.0", port=port)