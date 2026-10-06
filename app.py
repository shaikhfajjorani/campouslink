"""
CampusLink v4 - AI-powered Placement Management Platform

Run:
    python -m pip install -r requirements.txt
    python -m streamlit run app.py

Demo accounts:
    officer / officer123
    recruiter / recruiter123
    student / student123
    mentor / mentor123

Main additions in v4:
- Role-based authentication
- Student registration/profile management
- Resume upload + text extraction + resume scoring
- AI-style skill gap analysis and learning roadmap
- Placement readiness prediction
- Job/drive management
- Student applications and application pipeline
- Interview scheduling and results
- Notifications/inbox
- Placement analytics
- AI placement assistant
- Offer/document/joining tracking
- Mentor support
- Admin user management
- Audit log and privacy controls
"""

import hashlib
import io
import json
import re
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# Optional PDF extraction
try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

st.set_page_config(page_title="CampusLink v4", page_icon="🎓", layout="wide")

DB = "campuslink.db"

CAMPUSES = ["North Campus", "South Campus", "East Campus"]
BRANCHES = ["CSE", "IT", "ECE", "MECH", "CIVIL"]
SKILLS = [
    "Python", "Java", "SQL", "AWS", "Docker", "DSA", "Git",
    "Statistics", "Tableau", "Machine Learning", "React", "Linux",
    "REST API", "Power BI", "Excel", "TensorFlow"
]
DOMAINS = [
    "cloud migration", "web dashboard", "machine learning classifier",
    "data pipeline", "REST API", "mobile app"
]
COMPANIES = ["TechNova", "DataWiz", "BuildCore", "CloudNine"]
STATUSES = ["Applied", "Shortlisted", "Interview", "Selected", "Rejected", "Withdrawn"]
INTERVIEW_MODES = ["Online", "Offline"]
OFFER_STATUSES = ["Offered", "Accepted", "Deferred", "Withdrawn"]
DOC_STATUSES = ["Pending", "Submitted", "Verified"]
JOINING_STATUSES = ["Awaiting", "Confirmed"]


# ============================================================
# UTILITIES
# ============================================================
def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def today():
    return datetime.now().strftime("%Y-%m-%d")


def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()


def make_id(prefix, n):
    return f"{prefix}{n:04d}"


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def parse_skills(text):
    text = str(text or "")
    found = []
    for skill in SKILLS:
        if re.search(r"\b" + re.escape(skill) + r"\b", text, re.I):
            found.append(skill)
    return sorted(set(found))


def extract_pdf_text(file_bytes):
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(io.BytesIO(file_bytes))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception:
        return ""


# ============================================================
# DATABASE
# ============================================================
def db():
    return sqlite3.connect(DB, check_same_thread=False)


def init_db():
    with closing(db()) as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                student_id TEXT,
                company TEXT,
                campus TEXT,
                email TEXT,
                phone TEXT,
                active INTEGER DEFAULT 1,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS students (
                id TEXT PRIMARY KEY,
                name TEXT,
                email TEXT,
                phone TEXT,
                campus TEXT,
                branch TEXT,
                cgpa REAL,
                backlogs INTEGER,
                aptitude REAL,
                mock REAL,
                comm REAL,
                projects INTEGER,
                certs INTEGER,
                skills TEXT,
                resume_text TEXT,
                resume_name TEXT,
                resume_score REAL DEFAULT 0,
                resume_file BLOB,
                resume_mime TEXT,
                created_at TEXT
            );

            CREATE TABLE IF NOT EXISTS drives (
                id TEXT PRIMARY KEY,
                company TEXT,
                role TEXT,
                skills TEXT,
                min_cgpa REAL,
                branches TEXT,
                mock_bench REAL,
                salary_min REAL,
                salary_max REAL,
                openings INTEGER,
                deadline TEXT,
                date TEXT,
                slot TEXT,
                venue TEXT,
                mode TEXT,
                jd TEXT,
                status TEXT DEFAULT 'Open',
                created_by TEXT
            );

            CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY,
                student_id TEXT,
                drive_id TEXT,
                status TEXT,
                applied_at TEXT,
                updated_at TEXT,
                UNIQUE(student_id, drive_id)
            );

            CREATE TABLE IF NOT EXISTS interviews (
                id TEXT PRIMARY KEY,
                application_id TEXT,
                student_id TEXT,
                drive_id TEXT,
                interview_date TEXT,
                interview_time TEXT,
                mode TEXT,
                venue TEXT,
                meeting_link TEXT,
                panel TEXT,
                result TEXT DEFAULT 'Pending',
                feedback TEXT
            );

            CREATE TABLE IF NOT EXISTS offers (
                id TEXT PRIMARY KEY,
                student_id TEXT,
                company TEXT,
                role TEXT,
                ctc_lpa REAL,
                offer_status TEXT,
                docs_status TEXT,
                joining_status TEXT,
                ppo INTEGER DEFAULT 0,
                offer_date TEXT
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                to_id TEXT,
                kind TEXT,
                text TEXT,
                ts TEXT,
                read INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT,
                user TEXT,
                role TEXT,
                action TEXT
            );
            """
        )
        con.commit()


def query(sql, params=()):
    with closing(db()) as con:
        return pd.read_sql_query(sql, con, params=params)


def execute(sql, params=()):
    with closing(db()) as con:
        con.execute(sql, params)
        con.commit()


def executemany(sql, rows):
    with closing(db()) as con:
        con.executemany(sql, rows)
        con.commit()


def next_id(table, prefix):
    with closing(db()) as con:
        rows = con.execute(f"SELECT id FROM {table} WHERE id LIKE ?", (prefix + "%",)).fetchall()
    nums = []
    for r in rows:
        m = re.search(r"(\d+)$", str(r[0]))
        if m:
            nums.append(int(m.group(1)))
    return make_id(prefix, max(nums, default=0) + 1)


def audit(action):
    if "user" in st.session_state:
        u = st.session_state["user"]
        execute(
            "INSERT INTO audit(ts,user,role,action) VALUES(?,?,?,?)",
            (now(), u["username"], u["role"], action),
        )


def notify(to_id, kind, text):
    execute(
        "INSERT INTO messages(to_id,kind,text,ts,read) VALUES(?,?,?,?,0)",
        (to_id, kind, text, now()),
    )


# ============================================================
# SEED DATA & READINESS
# ============================================================
def readiness_score(s):
    try:
        cgpa = float(s["cgpa"]) if pd.notna(s["cgpa"]) else 0.0
        aptitude = float(s["aptitude"]) if pd.notna(s["aptitude"]) else 0.0
        mock = float(s["mock"]) if pd.notna(s["mock"]) else 0.0
        comm = float(s["comm"]) if pd.notna(s["comm"]) else 0.0
        projects = int(s["projects"]) if pd.notna(s["projects"]) else 0
        certs = int(s["certs"]) if pd.notna(s["certs"]) else 0
        backlogs = int(s["backlogs"]) if pd.notna(s["backlogs"]) else 0

        score = (
            cgpa / 10 * 25
            + aptitude * 0.25
            + mock * 0.20
            + comm * 0.15
            + min(projects, 4) / 4 * 7.5
            + min(certs, 3) / 3 * 7.5
            - backlogs * 4
        )
        return round(float(np.clip(score, 0, 100)), 1)
    except Exception:
        return 0.0


def readiness_level(score):
    if score < 45:
        return "Not Ready"
    if score < 60:
        return "Developing"
    if score < 75:
        return "Ready"
    return "Highly Employable"


EXPECTED_COLUMNS = {
    "users": {
        "email": "TEXT",
        "phone": "TEXT",
        "active": "INTEGER DEFAULT 1",
        "created_at": "TEXT",
    },
    "students": {
        "resume_text": "TEXT",
        "resume_name": "TEXT",
        "resume_score": "REAL DEFAULT 0",
        "resume_file": "BLOB",
        "resume_mime": "TEXT",
        "created_at": "TEXT",
    },
    "drives": {
        "skills": "TEXT",
        "min_cgpa": "REAL DEFAULT 0",
        "branches": "TEXT",
        "mock_bench": "REAL DEFAULT 0",
        "salary_min": "REAL DEFAULT 0",
        "salary_max": "REAL DEFAULT 0",
        "openings": "INTEGER DEFAULT 0",
        "deadline": "TEXT",
        "date": "TEXT",
        "slot": "TEXT",
        "venue": "TEXT",
        "mode": "TEXT DEFAULT 'Online'",
        "jd": "TEXT",
        "status": "TEXT DEFAULT 'Open'",
        "created_by": "TEXT",
    },
    "applications": {
        "student_id": "TEXT",
        "drive_id": "TEXT",
        "status": "TEXT DEFAULT 'Applied'",
        "applied_at": "TEXT",
        "updated_at": "TEXT",
    },
    "interviews": {
        "application_id": "TEXT",
        "student_id": "TEXT",
        "drive_id": "TEXT",
        "interview_date": "TEXT",
        "interview_time": "TEXT",
        "mode": "TEXT",
        "venue": "TEXT",
        "meeting_link": "TEXT",
        "panel": "TEXT",
        "result": "TEXT DEFAULT 'Pending'",
        "feedback": "TEXT",
    },
    "offers": {
        "id": "TEXT",
        "student_id": "TEXT",
        "company": "TEXT",
        "role": "TEXT",
        "ctc_lpa": "REAL DEFAULT 0",
        "offer_status": "TEXT DEFAULT 'Offered'",
        "docs_status": "TEXT DEFAULT 'Pending'",
        "joining_status": "TEXT DEFAULT 'Awaiting'",
        "ppo": "INTEGER DEFAULT 0",
        "offer_date": "TEXT",
    },
    "messages": {
        "id": "INTEGER",
        "to_id": "TEXT",
        "kind": "TEXT",
        "text": "TEXT",
        "ts": "TEXT",
        "read": "INTEGER DEFAULT 0",
    },
    "audit": {
        "id": "INTEGER",
        "ts": "TEXT",
        "user": "TEXT",
        "role": "TEXT",
        "action": "TEXT",
    },
}


def _add_missing_columns():
    with closing(db()) as con:
        for table, columns in EXPECTED_COLUMNS.items():
            tbl_exists = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not tbl_exists:
                continue
            
            existing = {str(row[1]).lower() for row in con.execute(f"PRAGMA table_info({table})").fetchall()}
            for column, definition in columns.items():
                if column.lower() not in existing:
                    try:
                        con.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
                    except Exception as e:
                        print(f"Note: Could not add column {column} to {table}: {e}")
        con.commit()

    with closing(db()) as con:
        con.execute("UPDATE drives SET status='Open' WHERE status IS NULL OR status=''")
        con.execute("UPDATE drives SET mode='Online' WHERE mode IS NULL OR mode=''")
        con.execute("UPDATE drives SET openings=0 WHERE openings IS NULL")
        con.execute("UPDATE drives SET salary_min=0 WHERE salary_min IS NULL")
        con.execute("UPDATE drives SET salary_max=0 WHERE salary_max IS NULL")
        con.execute("UPDATE messages SET read=0 WHERE read IS NULL")

        offer_cols = {str(row[1]).lower() for row in con.execute("PRAGMA table_info(offers)").fetchall()}
        if "id" in offer_cols:
            con.execute("""
                UPDATE offers
                SET id = 'O' || printf('%04d', rowid)
                WHERE id IS NULL OR id=''
            """)

        audit_cols = {str(row[1]).lower() for row in con.execute("PRAGMA table_info(audit)").fetchall()}
        if "id" in audit_cols:
            con.execute("""
                UPDATE audit
                SET id = rowid
                WHERE id IS NULL
            """)

        con.execute("UPDATE users SET active=1 WHERE active IS NULL")
        con.commit()


def migrate_database():
    _add_missing_columns()


init_db()
migrate_database()


def seed_database():
    users = [
        ("officer", hash_password("officer123"), "Placement Officer", None, None, None, "officer@campuslink.demo", "9000000001"),
        ("recruiter", hash_password("recruiter123"), "Recruiter", None, "TechNova", None, "recruiter@technova.demo", "9000000002"),
        ("student", hash_password("student123"), "Student", "S001", None, "North Campus", "student@campuslink.demo", "9000000003"),
        ("mentor", hash_password("mentor123"), "Mentor", None, None, "North Campus", "mentor@campuslink.demo", "9000000004"),
    ]
    for row in users:
        execute(
            """
            INSERT OR IGNORE INTO users
            (username,password_hash,role,student_id,company,campus,email,phone,created_at)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (*row, now()),
        )

    if query("SELECT COUNT(*) n FROM students").iloc[0]["n"] == 0:
        rng = np.random.default_rng(42)
        rows = []
        for i in range(1, 81):
            skills = list(rng.choice(SKILLS, size=int(rng.integers(4, 9)), replace=False))
            student = {
                "id": make_id("S", i),
                "name": "Student " + str(i),
                "email": f"student{i}@college.edu",
                "phone": f"91{9000000000+i}",
                "campus": rng.choice(CAMPUSES),
                "branch": rng.choice(BRANCHES, p=[.30, .25, .20, .15, .10]),
                "cgpa": round(float(np.clip(rng.normal(7.5, .8), 5, 9.8)), 2),
                "backlogs": int(rng.choice([0, 0, 0, 1, 2])),
                "aptitude": round(float(np.clip(rng.normal(65, 14), 20, 100)), 1),
                "mock": round(float(np.clip(rng.normal(62, 15), 15, 100)), 1),
                "comm": round(float(np.clip(rng.normal(63, 13), 20, 100)), 1),
                "projects": int(rng.integers(0, 5)),
                "certs": int(rng.integers(0, 4)),
                "skills": ", ".join(skills),
                "resume_text": "Skills: " + ", ".join(skills),
                "resume_name": "",
                "resume_score": 0,
                "created_at": now(),
            }
            rows.append(tuple(student.values()))
        executemany(
            """
            INSERT INTO students
            (id,name,email,phone,campus,branch,cgpa,backlogs,aptitude,mock,comm,projects,certs,
             skills,resume_text,resume_name,resume_score,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            rows,
        )

    execute(
        """
        UPDATE students SET name=?, email=?, phone=?, campus=?, branch=?
        WHERE id='S001'
        """,
        ("Demo Student", "student@campuslink.demo", "9000000003", "North Campus", "CSE"),
    )

    if query("SELECT COUNT(*) n FROM drives").iloc[0]["n"] == 0:
        drives = [
            ("D001", "TechNova", "Cloud Engineer", "Python, AWS, Docker, SQL",
             7.0, "CSE,IT,ECE", 60, 6, 14, 8, "2026-10-10", "2026-10-12", "Morning",
             "Auditorium", "Online", "Cloud migration and data pipeline role using Python, AWS, Docker and SQL.", "Open", "officer"),
            ("D002", "DataWiz", "Data Analyst", "Python, SQL, Statistics, Tableau",
             7.5, "CSE,IT", 55, 5, 12, 6, "2026-10-11", "2026-10-13", "Morning",
             "Seminar Hall", "Online", "Build dashboards, analytics pipelines and data models.", "Open", "officer"),
            ("D003", "BuildCore", "Software Developer", "Java, DSA, SQL, Git",
             6.5, "CSE,IT,ECE,MECH,CIVIL", 50, 4, 10, 12, "2026-10-14", "2026-10-15", "Afternoon",
             "Lab 1", "Offline", "Software development role focused on Java, DSA, APIs and Git.", "Open", "officer"),
        ]
        executemany(
            """
            INSERT INTO drives
            (id,company,role,skills,min_cgpa,branches,mock_bench,salary_min,salary_max,
             openings,deadline,date,slot,venue,mode,jd,status,created_by)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            drives,
        )

    if query("SELECT COUNT(*) n FROM applications").iloc[0]["n"] == 0:
        execute(
            """
            INSERT OR IGNORE INTO applications
            VALUES(?,?,?,?,?,?)
            """,
            ("A001", "S001", "D001", "Shortlisted", now(), now()),
        )

    if query("SELECT COUNT(*) n FROM offers").iloc[0]["n"] == 0:
        execute(
            """
            INSERT INTO offers
            (id,student_id,company,role,ctc_lpa,offer_status,docs_status,joining_status,ppo,offer_date)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            ("O001", "S001", "TechNova", "Cloud Engineer", 10.5, "Offered", "Submitted", "Awaiting", 0, today()),
        )


seed_database()


# ============================================================
# AUTHENTICATION
# ============================================================
def login_screen():
    st.title("🎓 CampusLink v4")
    st.caption("AI-powered placement management platform")

    left, right = st.columns([1.3, 1])
    with left:
        st.subheader("Sign in")
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Sign in", type="primary", use_container_width=True)

        if submitted:
            row = query(
                "SELECT * FROM users WHERE username=? AND active=1",
                (username.strip(),),
            )
            if not row.empty and row.iloc[0]["password_hash"] == hash_password(password):
                r = row.iloc[0]
                st.session_state.user = {
                    "username": r["username"],
                    "role": r["role"],
                    "student_id": r["student_id"],
                    "company": r["company"],
                    "campus": r["campus"],
                    "email": r["email"],
                }
                audit("login")
                st.rerun()
            else:
                st.error("Invalid username or password.")

    with right:
        st.info(
            "**Demo credentials**\n\n"
            "Officer: `officer / officer123`\n\n"
            "Recruiter: `recruiter / recruiter123`\n\n"
            "Student: `student / student123`\n\n"
            "Mentor: `mentor / mentor123`"
        )
        st.markdown(
            """
            **v4 includes**
            - Resume AI
            - Skill-gap roadmap
            - Applications
            - Interviews
            - Offers
            - Analytics
            - Notifications
            - Placement assistant
            """
        )

    st.stop()


if "user" not in st.session_state:
    login_screen()

U = st.session_state.user


# ============================================================
# DATA HELPERS
# ============================================================
def students_df():
    d = query("SELECT * FROM students")
    d["readiness"] = d.apply(readiness_score, axis=1)
    d["level"] = d["readiness"].apply(readiness_level)
    d["skill_count"] = d["skills"].fillna("").apply(lambda x: len([a for a in x.split(",") if a.strip()]))
    d["resume_score"] = pd.to_numeric(d["resume_score"], errors="coerce").fillna(0)
    return d


def drives_df():
    d = query("SELECT * FROM drives ORDER BY date")
    defaults = {
        "salary_min": 0.0, "salary_max": 0.0, "openings": 0,
        "deadline": "", "mode": "Online", "status": "Open",
        "date": "", "slot": "", "venue": "", "branches": "",
        "skills": "", "jd": "", "mock_bench": 60.0
    }
    for col, default in defaults.items():
        if col not in d.columns:
            d[col] = default
    return d


def applications_df():
    return query("SELECT * FROM applications")


def offers_df():
    d = query("SELECT * FROM offers")
    if "id" not in d.columns:
        d["id"] = [make_id("O", i + 1) for i in range(len(d))]
    if "offer_status" not in d.columns:
        d["offer_status"] = "Offered"
    if "docs_status" not in d.columns:
        d["docs_status"] = "Pending"
    if "joining_status" not in d.columns:
        d["joining_status"] = "Awaiting"
    return d


def student_row(sid):
    d = query("SELECT * FROM students WHERE id=?", (sid,))
    return d.iloc[0] if not d.empty else None


def drive_row(did):
    d = query("SELECT * FROM drives WHERE id=?", (did,))
    return d.iloc[0] if not d.empty else None


def drive_skills(d):
    return [x.strip() for x in str(d["skills"]).split(",") if x.strip()]


def student_skills(s):
    return [x.strip() for x in str(s["skills"]).split(",") if x.strip()]


def fit_analysis(s, d):
    ss = set(student_skills(s))
    req = set(drive_skills(d))
    missing = sorted(req - ss)
    matched = sorted(req & ss)
    skill_score = 35 * len(matched) / max(len(req), 1)
    readiness = readiness_score(s)
    readiness_points = 30 * readiness / 100
    mock_bench = float(d["mock_bench"]) if pd.notna(d["mock_bench"]) and float(d["mock_bench"]) > 0 else 60.0
    student_mock = float(s["mock"]) if pd.notna(s["mock"]) else 0.0
    mock_points = 20 * min(student_mock / mock_bench, 1)
    
    branch_ok = str(s["branch"]) in [x.strip() for x in str(d["branches"]).split(",")]
    cgpa_ok = float(s["cgpa"] if pd.notna(s["cgpa"]) else 0) >= float(d["min_cgpa"] if pd.notna(d["min_cgpa"]) else 0)
    backlogs_ok = int(s["backlogs"] if pd.notna(s["backlogs"]) else 0) == 0
    eligibility = branch_ok and cgpa_ok and backlogs_ok
    
    score = round(skill_score + readiness_points + mock_points + (15 if eligibility else 0), 1)
    return {
        "score": score,
        "missing": missing,
        "matched": matched,
        "eligibility": eligibility,
        "readiness": readiness,
        "skill_score": round(skill_score, 1),
        "readiness_points": round(readiness_points, 1),
        "mock_points": round(mock_points, 1),
        "branch_ok": branch_ok,
        "cgpa_ok": cgpa_ok,
    }


def resume_score(text):
    text = str(text or "")
    if not text.strip() or text.lower() == "nan":
        return 0, []
    score = 0
    feedback = []
    checks = [
        (r"\b(email|e-mail)\b", 10, "Contact email"),
        (r"\b(phone|mobile)\b", 5, "Phone/contact"),
        (r"\b(education|degree|btech|b\.tech|bachelor)\b", 15, "Education"),
        (r"\b(project|projects)\b", 15, "Projects"),
        (r"\b(skill|skills|technical skills)\b", 15, "Skills"),
        (r"\b(internship|experience|work experience)\b", 15, "Experience"),
        (r"\b(certification|certificate|certifications)\b", 10, "Certifications"),
        (r"\b(achievement|award)\b", 5, "Achievements"),
        (r"\b(github|linkedin)\b", 5, "Professional links"),
    ]
    for pattern, pts, label in checks:
        if re.search(pattern, text, re.I):
            score += pts
        else:
            feedback.append("Consider adding " + label)
    return min(score, 100), feedback


def recommendations(s):
    tips = []
    cgpa = float(s["cgpa"]) if pd.notna(s["cgpa"]) else 0.0
    aptitude = float(s["aptitude"]) if pd.notna(s["aptitude"]) else 0.0
    mock = float(s["mock"]) if pd.notna(s["mock"]) else 0.0
    comm = float(s["comm"]) if pd.notna(s["comm"]) else 0.0
    projects = int(s["projects"]) if pd.notna(s["projects"]) else 0
    certs = int(s["certs"]) if pd.notna(s["certs"]) else 0
    res_score = float(s["resume_score"]) if pd.notna(s["resume_score"]) else 0.0

    if cgpa < 7.5:
        tips.append("Strengthen academic performance and clear any backlogs.")
    if aptitude < 60:
        tips.append("Practice aptitude for 20–30 minutes daily.")
    if mock < 60:
        tips.append("Complete at least two mock interviews.")
    if comm < 60:
        tips.append("Practice concise technical and HR answers.")
    if projects < 2:
        tips.append("Build one practical project and publish it on GitHub.")
    if certs < 1:
        tips.append("Complete one role-relevant certification.")
    if res_score < 70:
        tips.append("Improve your resume using the Resume AI checklist.")
    return tips or ["Maintain consistency and apply to roles matching your strongest skills."]


# ============================================================
# SIDEBAR / NAVIGATION
# ============================================================
role = U["role"]

PAGE_MAP = {
    "Placement Officer": [
        "🏠 Command Center",
        "👥 Students",
        "💼 Drives",
        "📋 Applications",
        "🎤 Interviews",
        "📄 Offers",
        "📊 Analytics",
        "🤝 Support Hub",
        "📣 Notifications",
        "🔐 Admin & Audit",
    ],
    "Recruiter": [
        "🏠 Recruiter Dashboard",
        "💼 My Drives",
        "📋 Candidates",
        "🎤 Interviews",
        "📄 Offers",
    ],
    "Student": [
        "🏠 My Command Center",
        "👤 My Profile",
        "📄 Resume AI",
        "💼 Jobs & Apply",
        "📋 My Applications",
        "🎤 My Interviews",
        "💬 Placement Assistant",
        "🔔 Notifications",
    ],
    "Mentor": [
        "🏠 Mentor Dashboard",
        "🤝 Support Hub",
        "👥 Student 360",
        "📣 Notifications",
    ],
}

st.sidebar.title("🎓 CampusLink")
st.sidebar.caption(f"{U['username']} · {role}")

unread = 0
if U.get("student_id"):
    unread = safe_int(query("SELECT COUNT(*) n FROM messages WHERE to_id=? AND read=0", (U["student_id"],)).iloc[0]["n"])
if unread:
    st.sidebar.success(f"🔔 {unread} unread notification(s)")

page = st.sidebar.radio("Navigation", PAGE_MAP[role])

if st.sidebar.button("🚪 Sign out", use_container_width=True):
    audit("logout")
    del st.session_state["user"]
    st.rerun()


# ============================================================
# OFFICER COMMAND CENTER
# ============================================================
if page == "🏠 Command Center":
    st.title("Placement Command Center")
    s = students_df()
    a = applications_df()
    o = offers_df()

    cols = st.columns(6)
    metrics = [
        ("Students", len(s)),
        ("Ready ≥ 60", int((s["readiness"] >= 60).sum())),
        ("Applications", len(a)),
        ("Shortlisted", int((a["status"] == "Shortlisted").sum()) if not a.empty else 0),
        ("Offers", len(o)),
        ("Placed", int((o["offer_status"] == "Accepted").sum()) if not o.empty else 0),
    ]
    for c, (label, value) in zip(cols, metrics):
        c.metric(label, value)

    c1, c2 = st.columns(2)
    with c1:
        branch = s.groupby("branch").size().reset_index(name="students")
        st.plotly_chart(px.bar(branch, x="branch", y="students", title="Students by branch"), use_container_width=True)
    with c2:
        level = s["level"].value_counts().reset_index()
        level.columns = ["level", "students"]
        st.plotly_chart(px.pie(level, names="level", values="students", title="Placement readiness"), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        if not a.empty:
            app_status = a["status"].value_counts().reset_index()
            app_status.columns = ["status", "applications"]
            st.plotly_chart(px.bar(app_status, x="status", y="applications", title="Application pipeline"), use_container_width=True)
    with c2:
        if not o.empty:
            st.plotly_chart(px.histogram(o, x="ctc_lpa", nbins=12, title="Offer package distribution (LPA)"), use_container_width=True)

    st.subheader("⚠️ Students needing support")
    support = s[(s["readiness"] < 60) | (s["resume_score"] < 60)]
    st.dataframe(
        support[["id", "name", "branch", "cgpa", "readiness", "resume_score", "level"]].sort_values("readiness").head(15),
        hide_index=True,
        use_container_width=True,
    )


# ============================================================
# OFFICER STUDENTS
# ============================================================
elif page == "👥 Students":
    st.title("Student Management")
    s = students_df()

    q = st.text_input("Search student", placeholder="Name, ID, branch, skill...")
    campus = st.multiselect("Campus filter", CAMPUSES, default=CAMPUSES)
    branch = st.multiselect("Branch filter", BRANCHES, default=BRANCHES)

    v = s[s["campus"].isin(campus) & s["branch"].isin(branch)]
    if q:
        ql = q.lower()
        v = v[
            v.apply(
                lambda r: ql in " ".join(map(str, [
                    r["id"], r["name"], r["branch"], r["skills"]
                ])).lower(),
                axis=1,
            )
        ]

    st.dataframe(
        v[["id", "name", "email", "campus", "branch", "cgpa", "backlogs",
           "readiness", "level", "resume_score", "skills"]],
        hide_index=True,
        use_container_width=True,
    )

    st.subheader("Student 360")
    if not v.empty:
        sid = st.selectbox("Select student", v["id"].tolist())
        r = s[s["id"] == sid].iloc[0]
        c = st.columns(5)
        c[0].metric("Readiness", r["readiness"])
        c[1].metric("CGPA", r["cgpa"])
        c[2].metric("Aptitude", r["aptitude"])
        c[3].metric("Mock", r["mock"])
        c[4].metric("Resume", r["resume_score"])
        st.write(f"**{r['name']}** · {r['branch']} · {r['campus']}")
        st.write("**Skills:**", r["skills"])
        st.write("**AI recommendations:**")
        for x in recommendations(r):
            st.write("•", x)


# ============================================================
# DRIVES
# ============================================================
elif page in ("💼 Drives", "💼 My Drives"):
    st.title("Job & Drive Management")

    if role == "Placement Officer":
        with st.expander("➕ Create a new placement drive"):
            with st.form("new_drive"):
                c1, c2 = st.columns(2)
                company = c1.text_input("Company", "NewCo")
                job_role = c2.text_input("Role", "Software Engineer")
                skills_text = c1.text_input("Required skills", "Python, SQL, Git")
                min_cgpa = c2.number_input("Minimum CGPA", 0.0, 10.0, 6.5, 0.1)
                branches = c1.multiselect("Eligible branches", BRANCHES, default=["CSE", "IT"])
                salary_min = c2.number_input("Min CTC (LPA)", 0.0, 100.0, 5.0, 0.5)
                salary_max = c1.number_input("Max CTC (LPA)", 0.0, 100.0, 12.0, 0.5)
                openings = c2.number_input("Openings", 1, 1000, 10)
                deadline = st.date_input("Application deadline")
                drive_date = st.date_input("Drive/interview date")
                mode = st.selectbox("Mode", INTERVIEW_MODES)
                venue = st.text_input("Venue / platform", "Auditorium")
                jd = st.text_area("Job description", "Looking for a strong candidate...")
                create = st.form_submit_button("Create drive", type="primary")

            if create:
                did = next_id("drives", "D")
                execute(
                    """
                    INSERT INTO drives
                    (id,company,role,skills,min_cgpa,branches,mock_bench,salary_min,salary_max,
                     openings,deadline,date,slot,venue,mode,jd,status,created_by)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        did, company, job_role, skills_text, min_cgpa, ",".join(branches), 55,
                        salary_min, salary_max, openings, str(deadline), str(drive_date),
                        "Morning", venue, mode, jd, "Open", U["username"]
                    ),
                )
                audit(f"created drive {did}")
                st.success(f"Drive {did} created.")
                st.rerun()

    d = drives_df()
    if role == "Recruiter":
        d = d[d["company"] == U["company"]]

    if d.empty:
        st.info("No drives available.")
    else:
        st.dataframe(
            d[["id", "company", "role", "skills", "min_cgpa", "branches",
               "salary_min", "salary_max", "openings", "deadline", "date", "mode", "status"]],
            hide_index=True,
            use_container_width=True,
        )

        did = st.selectbox("View drive", d["id"].tolist())
        r = d[d["id"] == did].iloc[0]
        st.subheader(f"{r['company']} — {r['role']}")
        c = st.columns(5)
        c[0].metric("Min CGPA", r["min_cgpa"])
        c[1].metric("Salary", f'{r["salary_min"]}–{r["salary_max"]} LPA')
        c[2].metric("Openings", r["openings"])
        c[3].metric("Deadline", r["deadline"])
        c[4].metric("Mode", r["mode"])
        st.write("**Required skills:**", r["skills"])
        st.write("**Eligible branches:**", r["branches"])
        st.write("**Job description:**", r["jd"])


# ============================================================
# APPLICATIONS
# ============================================================
elif page in ("📋 Applications", "📋 Candidates", "📋 My Applications"):
    st.title("Application Management")
    apps = applications_df()
    s = students_df()
    d = drives_df()

    if role == "Student":
        sid = U["student_id"]
        my = apps[apps["student_id"] == sid]
        st.subheader("My application pipeline")
        if not my.empty:
            merged_my = my.merge(d[["id", "company", "role", "salary_min", "salary_max"]],
                                  left_on="drive_id", right_on="id", suffixes=("", "_drive"))
            st.dataframe(merged_my[["id", "company", "role", "status", "applied_at", "updated_at"]],
                         hide_index=True, use_container_width=True)
        else:
            st.info("You haven't submitted any applications yet.")

        st.subheader("Recommended jobs")
        student = student_row(sid)
        cards = []
        for _, dr in d[d["status"] == "Open"].iterrows():
            fit = fit_analysis(student, dr)
            if not ((apps["student_id"] == sid) & (apps["drive_id"] == dr["id"])).any():
                cards.append({
                    "id": dr["id"],
                    "company": dr["company"],
                    "role": dr["role"],
                    "fit": fit["score"],
                    "eligible": fit["eligibility"],
                    "missing": ", ".join(fit["missing"]) or "None",
                    "salary": f'{dr["salary_min"]}–{dr["salary_max"]} LPA',
                })
        rec = pd.DataFrame(cards).sort_values("fit", ascending=False) if cards else pd.DataFrame()
        if not rec.empty:
            st.dataframe(rec, hide_index=True, use_container_width=True)
            did = st.selectbox("Choose a job to apply", rec.id.tolist())
            dr = d[d["id"] == did].iloc[0]
            fit = fit_analysis(student, dr)
            st.write(f"**AI fit score:** {fit['score']}/100")
            if fit["eligibility"]:
                if st.button("🚀 Apply Now", type="primary"):
                    aid = next_id("applications", "A")
                    execute(
                        "INSERT OR IGNORE INTO applications VALUES(?,?,?,?,?,?)",
                        (aid, sid, did, "Applied", now(), now()),
                    )
                    notify(sid, "Application", f'Application submitted for {dr["company"]} — {dr["role"]}.')
                    audit(f"student applied to {did}")
                    st.success("Application submitted.")
                    st.rerun()
            else:
                st.warning("You are not currently eligible. See the skill/readiness gaps below.")
            if fit["missing"]:
                st.write("**Skill gap:**", ", ".join(fit["missing"]))
        else:
            st.info("No new recommended jobs.")

    else:
        if role == "Recruiter":
            company = U["company"]
            d_comp = d[d["company"] == company]
            if not apps.empty:
                apps = apps.merge(d_comp[["id", "company", "role"]], left_on="drive_id", right_on="id", suffixes=("", "_drive"))
        elif role == "Placement Officer":
            if not apps.empty:
                apps = apps.merge(d[["id", "company", "role"]], left_on="drive_id", right_on="id", suffixes=("", "_drive"))

        if not apps.empty:
            st.dataframe(apps, hide_index=True, use_container_width=True)
            aid = st.selectbox("Application to manage", apps["id"].tolist())
            ar = apps[apps["id"] == aid].iloc[0]

            if role in ("Placement Officer", "Recruiter"):
                current_status = ar["status"] if ar["status"] in STATUSES else STATUSES[0]
                new_status = st.selectbox("Update status", STATUSES, index=STATUSES.index(current_status))
                if st.button("Save application status"):
                    execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", (new_status, now(), aid))
                    notify(ar["student_id"], "Application update", f"Your application status is now: {new_status}.")
                    audit(f"updated application {aid} to {new_status}")
                    st.success("Application updated.")
                    st.rerun()
        else:
            st.info("No applications yet.")


# ============================================================
# INTERVIEWS
# ============================================================
elif page in ("🎤 Interviews", "🎤 My Interviews"):
    st.title("Interview Management")
    apps = applications_df()
    ints = query("SELECT * FROM interviews ORDER BY interview_date, interview_time")
    d = drives_df()

    if role == "Student":
        sid = U["student_id"]
        ints = ints[ints["student_id"] == sid] if not ints.empty else ints
        st.subheader("My interviews")
        if ints.empty:
            st.info("No interviews scheduled.")
        else:
            for _, r in ints.iterrows():
                with st.container(border=True):
                    st.write(f'### {r["drive_id"]} · {r["interview_date"]} {r["interview_time"]}')
                    st.write(f'**Mode:** {r["mode"]} · **Venue:** {r["venue"]}')
                    st.write(f'**Panel:** {r["panel"]} · **Result:** {r["result"]}')
                    if r["meeting_link"]:
                        st.code(r["meeting_link"])
                    if r["feedback"]:
                        st.info(r["feedback"])

    else:
        if role == "Recruiter":
            company_drives = d[d["company"] == U["company"]]
            if not ints.empty:
                ints = ints[ints["drive_id"].isin(company_drives["id"])]

        if not apps.empty and role in ("Placement Officer", "Recruiter"):
            with st.expander("➕ Schedule interview"):
                eligible_apps = apps[apps["status"].isin(["Shortlisted", "Interview"])]
                if not eligible_apps.empty:
                    aid = st.selectbox("Application", eligible_apps["id"].tolist())
                    dr_id = eligible_apps[eligible_apps["id"] == aid].iloc[0]["drive_id"]
                    sid = eligible_apps[eligible_apps["id"] == aid].iloc[0]["student_id"]
                    c1, c2 = st.columns(2)
                    date = c1.date_input("Interview date")
                    time = c2.time_input("Interview time")
                    mode = c1.selectbox("Mode", INTERVIEW_MODES)
                    venue = c2.text_input("Venue / meeting platform", "Google Meet")
                    link = st.text_input("Meeting link", "")
                    panel = st.text_input("Panel", "Panel A")
                    if st.button("Schedule interview", type="primary"):
                        iid = next_id("interviews", "I")
                        execute(
                            """
                            INSERT INTO interviews
                            (id,application_id,student_id,drive_id,interview_date,interview_time,mode,venue,meeting_link,panel)
                            VALUES(?,?,?,?,?,?,?,?,?,?)
                            """,
                            (iid, aid, sid, dr_id, str(date), str(time), mode, venue, link, panel),
                        )
                        execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", ("Interview", now(), aid))
                        notify(sid, "Interview scheduled", f"Interview scheduled on {date} at {time}.")
                        audit(f"scheduled interview {iid}")
                        st.success("Interview scheduled.")
                        st.rerun()

        if not ints.empty:
            st.dataframe(ints, hide_index=True, use_container_width=True)
            iid = st.selectbox("Interview to update", ints["id"].tolist())
            ir = ints[ints["id"] == iid].iloc[0]
            res_options = ["Pending", "Selected", "Rejected"]
            cur_res = ir["result"] if ir["result"] in res_options else "Pending"
            result = st.selectbox("Result", res_options, index=res_options.index(cur_res))
            feedback_val = str(ir["feedback"]) if pd.notna(ir["feedback"]) else ""
            feedback = st.text_area("Interview feedback", feedback_val)
            if st.button("Save interview result"):
                execute("UPDATE interviews SET result=?,feedback=? WHERE id=?", (result, feedback, iid))
                if result == "Selected":
                    execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", ("Selected", now(), ir["application_id"]))
                    notify(ir["student_id"], "Interview result", "Congratulations! You have been selected after the interview.")
                elif result == "Rejected":
                    execute("UPDATE applications SET status=?,updated_at=? WHERE id=?", ("Rejected", now(), ir["application_id"]))
                    notify(ir["student_id"], "Interview result", "Your interview result has been updated. Keep applying and improving.")
                audit(f"updated interview {iid} result={result}")
                st.success("Interview result saved.")
                st.rerun()
        else:
            st.info("No interviews found.")


# ============================================================
# OFFERS
# ============================================================
elif page in ("📄 Offers",):
    st.title("Offers, Documents & Joining")
    o = offers_df()

    if role == "Recruiter":
        o = o[o["company"] == U["company"]]

    if not o.empty:
        st.dataframe(o, hide_index=True, use_container_width=True)

        if role == "Placement Officer":
            st.subheader("Update offer")
            oid = st.selectbox("Offer", o["id"].tolist())
            r = o[o["id"] == oid].iloc[0]
            c = st.columns(3)
            off_stat = r["offer_status"] if r["offer_status"] in OFFER_STATUSES else OFFER_STATUSES[0]
            doc_stat = r["docs_status"] if r["docs_status"] in DOC_STATUSES else DOC_STATUSES[0]
            join_stat = r["joining_status"] if r["joining_status"] in JOINING_STATUSES else JOINING_STATUSES[0]

            offer_status = c[0].selectbox("Offer status", OFFER_STATUSES, index=OFFER_STATUSES.index(off_stat))
            docs = c[1].selectbox("Documents", DOC_STATUSES, index=DOC_STATUSES.index(doc_stat))
            joining = c[2].selectbox("Joining", JOINING_STATUSES, index=JOINING_STATUSES.index(join_stat))
            if st.button("Save offer"):
                execute(
                    "UPDATE offers SET offer_status=?,docs_status=?,joining_status=? WHERE id=?",
                    (offer_status, docs, joining, oid),
                )
                notify(r["student_id"], "Offer update", f"Offer status: {offer_status}; documents: {docs}; joining: {joining}.")
                audit(f"updated offer {oid}")
                st.success("Offer updated.")
                st.rerun()
    else:
        st.info("No offers found.")


# ============================================================
# ANALYTICS
# ============================================================
elif page == "📊 Analytics":
    st.title("Placement Analytics")
    s = students_df()
    a = applications_df()
    o = offers_df()
    d_df = drives_df()

    placed = int((o["offer_status"] == "Accepted").sum()) if not o.empty else 0
    placement_rate = round(100 * placed / max(len(s), 1), 1)

    c = st.columns(6)
    c[0].metric("Placement rate", f"{placement_rate}%")
    c[1].metric("Average readiness", f'{s["readiness"].mean():.1f}')
    c[2].metric("Average CGPA", f'{s["cgpa"].mean():.2f}')
    c[3].metric("Average package", f'{o["ctc_lpa"].mean():.1f} LPA' if not o.empty else "0")
    c[4].metric("Highest package", f'{o["ctc_lpa"].max():.1f} LPA' if not o.empty else "0")
    c[5].metric("Open drives", int((d_df.status == "Open").sum()) if not d_df.empty else 0)

    c1, c2 = st.columns(2)
    with c1:
        br = s.groupby("branch").agg(students=("id", "count"), readiness=("readiness", "mean")).reset_index()
        st.plotly_chart(px.bar(br, x="branch", y="readiness", title="Average readiness by branch"), use_container_width=True)
    with c2:
        if not o.empty:
            st.plotly_chart(px.box(o, x="company", y="ctc_lpa", title="Package spread by company"), use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        skills = pd.Series(sum([student_skills(row) for _, row in s.iterrows()], []))
        if not skills.empty:
            skill_counts = skills.value_counts().reset_index()
            skill_counts.columns = ["skill", "students"]
            st.plotly_chart(px.bar(skill_counts.head(12), x="students", y="skill", orientation="h",
                                   title="Top student skills"), use_container_width=True)
    with c2:
        if not a.empty:
            funnel = a["status"].value_counts().reindex(STATUSES, fill_value=0).reset_index()
            funnel.columns = ["stage", "count"]
            fig = go.Figure(go.Funnel(y=funnel.stage, x=funnel["count"]))
            fig.update_layout(title="Application conversion funnel")
            st.plotly_chart(fig, use_container_width=True)

    st.subheader("Branch placement readiness table")
    st.dataframe(
        s.groupby(["branch", "level"]).size().reset_index(name="students"),
        hide_index=True, use_container_width=True
    )


# ============================================================
# SUPPORT HUB
# ============================================================
elif page in ("🤝 Support Hub", "👥 Student 360"):
    st.title("Mentor Support Hub")
    s = students_df()
    if role == "Mentor":
        s = s[s["campus"] == U["campus"]]

    support = s[(s["readiness"] < 60) | (s["resume_score"] < 60)].sort_values("readiness")
    st.caption("AI recommendations are guidance only; human mentors make the final decision.")

    st.dataframe(
        support[["id", "name", "branch", "campus", "readiness", "level", "resume_score", "skills"]],
        hide_index=True, use_container_width=True
    )

    if not support.empty:
        sid = st.selectbox("Student", support.id.tolist())
        r = s[s["id"] == sid].iloc[0]
        st.subheader(f"{r['name']} · {r['id']}")
        for tip in recommendations(r):
            st.write("•", tip)

        message = st.text_area("Mentor message", "Let's plan your next placement steps.")
        if st.button("Send mentor message"):
            notify(sid, "Mentor", message)
            audit(f"mentor message to {sid}")
            st.success("Message sent.")


# ============================================================
# NOTIFICATIONS
# ============================================================
elif page in ("📣 Notifications", "🔔 Notifications"):
    st.title("Notifications & Communication")

    if role == "Student":
        sid = U["student_id"]
        msgs = query("SELECT * FROM messages WHERE to_id=? ORDER BY id DESC", (sid,))
        if not msgs.empty:
            for _, m in msgs.iterrows():
                st.info(f"**{m['kind']}** · {m['ts']}\n\n{m['text']}")
            execute("UPDATE messages SET read=1 WHERE to_id=?", (sid,))
        else:
            st.success("No notifications.")
    else:
        st.subheader("Send announcement")
        target = st.selectbox("Target", ["All students"] + CAMPUSES)
        text_msg = st.text_area("Message", "Placement drive update...")
        if st.button("Send notification", type="primary"):
            s = students_df()
            if target != "All students":
                s = s[s["campus"] == target]
            for sid in s["id"]:
                notify(sid, "Announcement", text_msg)
            audit(f"announcement to {target}, count={len(s)}")
            st.success(f"Sent to {len(s)} students.")


# ============================================================
# STUDENT COMMAND CENTER
# ============================================================
elif page == "🏠 My Command Center":
    st.title("My Placement Command Center")
    s = student_row(U["student_id"])
    apps = applications_df()
    my_apps = apps[apps["student_id"] == U["student_id"]] if not apps.empty else apps
    offers = offers_df()
    my_offers = offers[offers.student_id == U["student_id"]] if not offers.empty else offers
    ints = query("SELECT * FROM interviews WHERE student_id=?", (U["student_id"],))

    score = readiness_score(s)
    level = readiness_level(score)

    c = st.columns(6)
    c[0].metric("Readiness", f"{score}%")
    c[1].metric("Level", level)
    c[2].metric("Applications", len(my_apps))
    c[3].metric("Shortlisted", int((my_apps["status"] == "Shortlisted").sum()) if not my_apps.empty else 0)
    c[4].metric("Interviews", len(ints))
    c[5].metric("Offers", len(my_offers))

    st.progress(score / 100, text=f"Placement readiness: {score}%")

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("🎯 Your next steps")
        for tip in recommendations(s):
            st.write("•", tip)
    with c2:
        st.subheader("📈 Your skill profile")
        vals = {
            "Aptitude": float(s["aptitude"]) if pd.notna(s["aptitude"]) else 0,
            "Mock": float(s["mock"]) if pd.notna(s["mock"]) else 0,
            "Communication": float(s["comm"]) if pd.notna(s["comm"]) else 0,
            "CGPA": float(s["cgpa"] if pd.notna(s["cgpa"]) else 0) * 10,
            "Resume": float(s["resume_score"]) if pd.notna(s["resume_score"]) else 0,
        }
        st.plotly_chart(px.bar(pd.DataFrame({"metric": list(vals), "score": list(vals.values())}),
                               x="metric", y="score", range_y=[0, 100]), use_container_width=True)

    if not my_offers.empty:
        st.success(f"🎉 You have {len(my_offers)} offer(s).")


# ============================================================
# STUDENT PROFILE
# ============================================================
elif page == "👤 My Profile":
    st.title("My Profile")
    sid = U["student_id"]
    s = student_row(sid)

    with st.form("profile"):
        c1, c2 = st.columns(2)
        name = c1.text_input("Name", str(s["name"]) if pd.notna(s["name"]) else "")
        email = c2.text_input("Email", str(s["email"]) if pd.notna(s["email"]) else "")
        phone = c1.text_input("Phone", str(s["phone"]) if pd.notna(s["phone"]) else "")
        
        campus_idx = CAMPUSES.index(s["campus"]) if pd.notna(s["campus"]) and s["campus"] in CAMPUSES else 0
        campus = c2.selectbox("Campus", CAMPUSES, index=campus_idx)
        
        branch_idx = BRANCHES.index(s["branch"]) if pd.notna(s["branch"]) and s["branch"] in BRANCHES else 0
        branch = c1.selectbox("Branch", BRANCHES, index=branch_idx)
        
        cgpa = c2.number_input("CGPA", 0.0, 10.0, float(s["cgpa"]) if pd.notna(s["cgpa"]) else 7.0, 0.01)
        backlogs = c1.number_input("Backlogs", 0, 20, int(s["backlogs"]) if pd.notna(s["backlogs"]) else 0)
        aptitude = c2.slider("Aptitude", 0, 100, int(s["aptitude"]) if pd.notna(s["aptitude"]) else 50)
        mock = c1.slider("Mock interview", 0, 100, int(s["mock"]) if pd.notna(s["mock"]) else 50)
        comm = c2.slider("Communication", 0, 100, int(s["comm"]) if pd.notna(s["comm"]) else 50)
        projects = c1.number_input("Projects", 0, 20, int(s["projects"]) if pd.notna(s["projects"]) else 0)
        certs = c2.number_input("Certifications", 0, 20, int(s["certs"]) if pd.notna(s["certs"]) else 0)
        skills = st.text_input("Skills (comma separated)", str(s["skills"]) if pd.notna(s["skills"]) else "")
        save_profile = st.form_submit_button("Save profile", type="primary")

    if save_profile:
        execute(
            """
            UPDATE students SET name=?,email=?,phone=?,campus=?,branch=?,cgpa=?,backlogs=?,
            aptitude=?,mock=?,comm=?,projects=?,certs=?,skills=? WHERE id=?
            """,
            (name, email, phone, campus, branch, cgpa, backlogs, aptitude, mock, comm, projects, certs, skills, sid),
        )
        audit("updated own profile")
        st.success("Profile saved.")
        st.rerun()


# ============================================================
# RESUME AI
# ============================================================
elif page == "📄 Resume AI":
    st.title("🤖 Resume AI")
    sid = U["student_id"]
    s = student_row(sid)

    st.write(
        "Upload your latest PDF/TXT resume. CampusLink stores the uploaded resume, "
        "extracts text, detects skills, scores the resume, and uses it for placement-fit analysis."
    )

    if pd.notna(s.get("resume_name")) and s["resume_name"]:
        st.info(f'Current resume: {s["resume_name"]}')

    if pd.notna(s.get("resume_file")) and s["resume_file"]:
        st.success("A resume file is already stored in CampusLink.")
        st.download_button(
            "⬇️ Download stored resume",
            data=s["resume_file"],
            file_name=str(s["resume_name"]) if pd.notna(s["resume_name"]) else "resume.pdf",
            mime=str(s["resume_mime"]) if pd.notna(s["resume_mime"]) else "application/pdf",
            key="download_stored_resume",
        )

    uploaded = st.file_uploader(
        "Upload resume",
        type=["pdf", "txt"],
        help="PDF is recommended. For scanned/image-only PDFs, paste the resume text below if extraction returns empty.",
    )
    
    default_resume_text = str(s["resume_text"]) if pd.notna(s["resume_text"]) else ""
    pasted = st.text_area(
        "Or paste resume text",
        default_resume_text,
        height=220,
    )

    if uploaded:
        st.caption(f"Selected file: {uploaded.name} ({len(uploaded.getvalue()) / 1024:.1f} KB)")

    if st.button("Analyze & Save Resume", type="primary"):
        text_content = pasted.strip()
        filename = str(s["resume_name"]) if pd.notna(s["resume_name"]) else ""
        file_bytes = s["resume_file"] if "resume_file" in s and pd.notna(s["resume_file"]) else None
        mime_type = str(s["resume_mime"]) if "resume_mime" in s and pd.notna(s["resume_mime"]) else ""

        if uploaded:
            filename = uploaded.name
            file_bytes = uploaded.getvalue()
            mime_type = uploaded.type or (
                "application/pdf" if uploaded.name.lower().endswith(".pdf") else "text/plain"
            )

            if uploaded.name.lower().endswith(".pdf"):
                extracted = extract_pdf_text(file_bytes)
                if extracted.strip():
                    text_content = extracted.strip()
                elif not text_content:
                    st.warning(
                        "No text could be extracted from this PDF. It may be scanned/image-based. "
                        "Please paste the resume text below and analyze again."
                    )
            else:
                text_content = file_bytes.decode("utf-8", errors="ignore").strip()

        if not text_content:
            st.error("Please upload a readable PDF/TXT resume or paste your resume text.")
            st.stop()

        score, feedback = resume_score(text_content)
        found = parse_skills(text_content)
        existing_skills = student_skills(s)
        merged_skills = sorted(set(existing_skills + found))

        execute(
            """
            UPDATE students
            SET resume_text=?, resume_name=?, resume_score=?, skills=?, resume_file=?, resume_mime=?
            WHERE id=?
            """,
            (
                text_content,
                filename,
                score,
                ", ".join(merged_skills),
                sqlite3.Binary(file_bytes) if file_bytes else None,
                mime_type,
                sid,
            ),
        )
        audit("analyzed and saved resume")
        st.success(f"Resume saved successfully. Score: {score}/100")
        st.rerun()

    current = student_row(sid)
    rs, feedback = resume_score(current["resume_text"])
    st.metric("Resume score", rs)
    st.progress(max(0, min(100, int(rs))) / 100)

    if feedback:
        st.subheader("AI improvement checklist")
        for x in feedback:
            st.write("•", x)
    else:
        st.success("Your resume contains the major recommended sections.")

    found = parse_skills(current["resume_text"])
    st.subheader("Detected skills")
    st.write(", ".join(found) if found else "No known skills detected yet.")

    st.subheader("Role readiness")
    for _, d_row in drives_df().iterrows():
        f = fit_analysis(current, d_row)
        with st.expander(f"{d_row['company']} — {d_row['role']} · Fit {f['score']}/100"):
            st.write("Matched:", ", ".join(f["matched"]) or "None")
            st.write("Missing:", ", ".join(f["missing"]) or "None")
            st.write("Eligible:", "Yes" if f["eligibility"] else "Not yet")


# ============================================================
# PLACEMENT ASSISTANT
# ============================================================
elif page == "💬 Placement Assistant":
    st.title("💬 AI Placement Assistant")
    st.caption("Ask about eligibility, readiness, skill gaps, jobs, interviews or packages.")

    s = student_row(U["student_id"])
    q = st.chat_input("Example: Which jobs should I apply for?")
    if q:
        ql = q.lower()
        if "readiness" in ql or "score" in ql:
            answer = f"Your readiness is **{readiness_score(s)}% ({readiness_level(readiness_score(s))})**."
        elif "skill" in ql or "gap" in ql:
            all_missing = {}
            for _, d_row in drives_df().iterrows():
                f = fit_analysis(s, d_row)
                for x in f["missing"]:
                    all_missing[x] = all_missing.get(x, 0) + 1
            top = sorted(all_missing, key=all_missing.get, reverse=True)[:5]
            answer = "Your most useful skill improvements are: " + (", ".join(top) if top else "No major gaps detected.")
        elif "eligible" in ql or "job" in ql or "company" in ql:
            rows = []
            for _, d_row in drives_df().iterrows():
                f = fit_analysis(s, d_row)
                if f["eligibility"]:
                    rows.append(f"{d_row['company']} — {d_row['role']} (fit {f['score']})")
            answer = "Eligible jobs:\n\n" + "\n".join("• " + x for x in rows) if rows else "No currently eligible jobs. Improve the gaps shown in Resume AI."
        elif "package" in ql or "salary" in ql or "ctc" in ql:
            o = offers_df()
            answer = f'Across current offers, average CTC is {o["ctc_lpa"].mean():.1f} LPA and highest is {o["ctc_lpa"].max():.1f} LPA.' if not o.empty else "No offer data yet."
        else:
            answer = "Try asking: What is my readiness? Which jobs am I eligible for? What skills should I improve? What is the average package?"

        st.chat_message("user").write(q)
        st.chat_message("assistant").write(answer)


# ============================================================
# ADMIN / AUDIT
# ============================================================
elif page == "🔐 Admin & Audit":
    st.title("Admin, Security & Audit")

    st.subheader("Create user")
    with st.form("create_user"):
        username = st.text_input("Username")
        password = st.text_input("Temporary password", type="password")
        new_role = st.selectbox("Role", ["Student", "Recruiter", "Mentor", "Placement Officer"])
        student_id = st.text_input("Student ID (for student role)", "")
        company = st.text_input("Company (for recruiter)", "")
        campus = st.selectbox("Campus", CAMPUSES)
        email = st.text_input("Email")
        create = st.form_submit_button("Create user")

    if create:
        exists = query("SELECT username FROM users WHERE username=?", (username,))
        if exists.empty and username and password:
            execute(
                """
                INSERT INTO users
                (username,password_hash,role,student_id,company,campus,email,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (username, hash_password(password), new_role, student_id or None,
                 company or None, campus, email, now()),
            )
            audit(f"created user {username}")
            st.success("User created.")
        else:
            st.error("Username already exists or required fields are missing.")

    st.subheader("Users")
    users = query("SELECT username,role,student_id,company,campus,email,active,created_at FROM users")
    st.dataframe(users, hide_index=True, use_container_width=True)

    st.subheader("Audit log")
    logs = query("SELECT * FROM audit ORDER BY id DESC, ts DESC LIMIT 100")
    st.dataframe(logs, hide_index=True, use_container_width=True)

    st.subheader("Privacy controls")
    st.markdown(
        """
        - Passwords are stored as SHA-256 hashes, not plain text.
        - Access is role-based.
        - Recruiters should only receive candidate information needed for hiring.
        - AI scores are advisory and should not be the sole basis for rejection.
        - Sensitive attributes should not be used for placement prediction.
        - Keep regular database backups before production deployment.
        """
    )


# ============================================================
# MENTOR DASHBOARD
# ============================================================
elif page == "🏠 Mentor Dashboard":
    st.title("Mentor Dashboard")
    s = students_df()
    s = s[s["campus"] == U["campus"]]

    c = st.columns(4)
    c[0].metric("Students", len(s))
    c[1].metric("Need support", int(((s["readiness"] < 60) | (s["resume_score"] < 60)).sum()))
    c[2].metric("Avg readiness", f'{s["readiness"].mean():.1f}')
    c[3].metric("Avg resume", f'{s["resume_score"].mean():.1f}')

    st.plotly_chart(
        px.scatter(s, x="readiness", y="resume_score", size="projects", color="branch",
                   hover_name="name", title="Readiness vs Resume Score"),
        use_container_width=True,
    )

else:
    st.info("Page under construction.")