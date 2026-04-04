from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import sqlite3
import random
import hashlib
import os
from functools import wraps

app = Flask(__name__)
app.secret_key = 'faculty_timetable_secret_2024'

DATABASE = 'faculty_system.db'

# ─────────────────────────────────────────────
# WORKLOAD LIMITS
# ─────────────────────────────────────────────
WORKLOAD_LIMITS = {
    'HOD': 8,
    'Professor': 12,
    'Assistant Professor': 16
}

LAB_BATCHES = 4   # max lab batches per lab subject
SEMESTERS = [2, 4, 6]

# ─────────────────────────────────────────────
# Timetable structure
#   1 period = 1 hour
#   9:30 start | break 11:30–11:45 | lunch 1:45–2:45 | end 4:45
#   Saturday ends at 1:45
# ─────────────────────────────────────────────
DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']

PERIODS = [
    {'id': 1, 'label': '9:30 – 10:30',   'type': 'theory'},
    {'id': 2, 'label': '10:30 – 11:30',  'type': 'theory'},
    {'id': 3, 'label': '11:30 – 11:45',  'type': 'break',  'name': 'Short Break'},
    {'id': 4, 'label': '11:45 – 12:45',  'type': 'theory'},
    {'id': 5, 'label': '12:45 – 1:45',   'type': 'theory'},
    {'id': 6, 'label': '1:45 – 2:45',    'type': 'lunch',  'name': 'Lunch Break'},
    {'id': 7, 'label': '2:45 – 3:45',    'type': 'theory'},
    {'id': 8, 'label': '3:45 – 4:45',    'type': 'theory'},
]

# On Saturday, only periods up to P5 (9:30 - 1:45) are available.
# P6 is Lunch, then it ends.
SATURDAY_MAX_PERIOD_ID = 5

TEACHING_PERIOD_IDS = [p['id'] for p in PERIODS if p['type'] == 'theory']

# ─────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.executescript('''
        CREATE TABLE IF NOT EXISTS faculty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ("HOD","Professor","Assistant Professor")),
            department TEXT NOT NULL,
            max_workload INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS subject (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            department TEXT NOT NULL,
            credits INTEGER NOT NULL DEFAULT 3,
            hours_per_week INTEGER NOT NULL,
            semester INTEGER NOT NULL,
            is_lab INTEGER NOT NULL DEFAULT 0,
            UNIQUE(name, department, semester)
        );

        CREATE TABLE IF NOT EXISTS faculty_preference (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
            subject_id INTEGER NOT NULL REFERENCES subject(id) ON DELETE CASCADE,
            UNIQUE(faculty_id, subject_id)
        );

        -- batch_no: NULL = theory, 1-4 = lab batch number
        CREATE TABLE IF NOT EXISTS allocation (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            faculty_id INTEGER NOT NULL REFERENCES faculty(id) ON DELETE CASCADE,
            subject_id INTEGER NOT NULL REFERENCES subject(id) ON DELETE CASCADE,
            batch_no INTEGER DEFAULT NULL,
            UNIQUE(faculty_id, subject_id, batch_no)
        );

        -- batch_no: 0 = theory/fixed (unique per slot), 1-4 = lab batch (parallel slots)
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            period_id INTEGER NOT NULL,
            semester INTEGER NOT NULL,
            faculty_id INTEGER REFERENCES faculty(id) ON DELETE SET NULL,
            subject_id INTEGER REFERENCES subject(id) ON DELETE SET NULL,
            batch_no INTEGER NOT NULL DEFAULT 0,
            is_fixed INTEGER NOT NULL DEFAULT 0,
            UNIQUE(day, period_id, semester, batch_no)
        );

        CREATE TABLE IF NOT EXISTS fixed_schedule (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            day TEXT NOT NULL,
            period_id INTEGER NOT NULL,
            semester INTEGER NOT NULL,
            subject_name TEXT NOT NULL,
            UNIQUE(day, period_id, semester)
        );

        CREATE TABLE IF NOT EXISTS admin (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        );
    ''')

    # Seed admin
    admin_pw = hash_password('admin123')
    c.execute("INSERT OR IGNORE INTO admin(username,password) VALUES(?,?)", ('admin', admin_pw))

    # Sample Fixed slots for each semester
    # 2nd Sem: Maths Mon P1, Wed P1
    # 4th Sem: Placement Thu P7+P8, Fri P7+P8
    # 6th Sem: Maths Mon P2, Wed P2
    fixed_seeds = [
        ('Monday', 1, 2, 'Maths'),
        ('Wednesday', 1, 2, 'Maths'),
        ('Thursday', 7, 4, 'Placement Training'),
        ('Thursday', 8, 4, 'Placement Training'),
        ('Friday', 7, 4, 'Placement Training'),
        ('Friday', 8, 4, 'Placement Training'),
        ('Monday', 2, 6, 'Maths'),
        ('Wednesday', 2, 6, 'Maths'),
    ]
    # Fixed seeds based on images (e.g. Placement/Employability Skills)
    fixed_seeds = [
        ('Friday', 1, 4, 'Employability Enhancement Skills'),
        ('Friday', 2, 4, 'Employability Enhancement Skills'),
    ]
    for d, p, s, name in fixed_seeds:
        c.execute("INSERT OR IGNORE INTO fixed_schedule(day,period_id,semester,subject_name) VALUES(?,?,?,?)", (d, p, s, name))

    # Real faculty from images
    faculty_list = [
        ('Prof. Shilpa S',      'shilpa@college.edu',  hash_password('pass123'), 'Assistant Professor', 'COMPUTER SCIENCE', 16),
        ('Prof. Bindulakshmi K V', 'bindu@college.edu',   hash_password('pass123'), 'Professor',           'COMPUTER SCIENCE', 12),
        ('Prof. Swathy Denesh', 'swathy@college.edu',  hash_password('pass123'), 'Assistant Professor', 'COMPUTER SCIENCE', 14),
        ('Dr. R Girisha',       'girisha@college.edu', hash_password('pass123'), 'Professor',           'COMPUTER SCIENCE', 12),
        ('Prof. Puttaswamy B S', 'putta@college.edu',   hash_password('pass123'), 'Professor',           'COMPUTER SCIENCE', 12),
        ('Prof. Reethushree K C', 'reethu@college.edu',  hash_password('pass123'), 'Assistant Professor', 'COMPUTER SCIENCE', 14),
        ('Dr. Geethanjali T M', 'geetha@college.edu',  hash_password('pass123'), 'HOD',               'COMPUTER SCIENCE', 8),
        ('Prof. Kampana M',     'kampana@college.edu', hash_password('pass123'), 'Assistant Professor', 'COMPUTER SCIENCE', 16),
    ]
    for f in faculty_list:
        c.execute("INSERT OR IGNORE INTO faculty(name,email,password,role,department,max_workload) VALUES(?,?,?,?,?,?)", f)

    # Real subjects from images
    # Semester 2: Only Python (Shilpa S)
    c.execute("INSERT OR IGNORE INTO subject(name,department,credits,hours_per_week,semester,is_lab) VALUES(?,?,?,?,?,?)", 
             ('Python Programming', 'COMPUTER SCIENCE', 3, 4, 2, 0))
    c.execute("INSERT OR IGNORE INTO subject(name,department,credits,hours_per_week,semester,is_lab) VALUES(?,?,?,?,?,?)", 
             ('Python Programming Laboratory', 'COMPUTER SCIENCE', 1, 2, 2, 1))

    # Semester 4: Subjects 1-10
    sem4_subjects = [
        ('Linear Algebra',                       'COMPUTER SCIENCE', 3, 4, 4, 0),
        ('Formal Language & Automata Theory',    'COMPUTER SCIENCE', 3, 4, 4, 0),
        ('Design & Analysis of Algorithms',      'COMPUTER SCIENCE', 3, 4, 4, 0),
        ('Innovation & IP Management',           'COMPUTER SCIENCE', 2, 3, 4, 0),
        ('Database Management System',           'COMPUTER SCIENCE', 3, 4, 4, 0),
        ('Financial Management',                 'COMPUTER SCIENCE', 3, 4, 4, 0),
        ('DAA Laboratory',                       'COMPUTER SCIENCE', 1, 2, 4, 1),
        ('DBMS Laboratory',                       'COMPUTER SCIENCE', 1, 2, 4, 1),
        ('FM Laboratory',                        'COMPUTER SCIENCE', 1, 2, 4, 1),
        ('Employability Enhancement Skills',     'COMPUTER SCIENCE', 1, 2, 4, 0),
    ]
    for s in sem4_subjects:
        c.execute("INSERT OR IGNORE INTO subject(name,department,credits,hours_per_week,semester,is_lab) VALUES(?,?,?,?,?,?)", s)

    # Semester 6: Subjects 1-9
    sem6_subjects = [
        ('Machine Learning',              'COMPUTER SCIENCE', 3, 4, 6, 0),
        ('Marketing Management & Research', 'COMPUTER SCIENCE', 3, 4, 6, 0),
        ('Natural Language Processing',    'COMPUTER SCIENCE', 3, 4, 6, 0),
        ('Financial Management (OE)',      'COMPUTER SCIENCE', 3, 4, 6, 0),
        ('Business Information Systems',   'COMPUTER SCIENCE', 3, 4, 6, 0),
        ('ML Laboratory',                 'COMPUTER SCIENCE', 1, 2, 6, 1),
        ('Mini Project',                  'COMPUTER SCIENCE', 2, 4, 6, 1),
        ('Employability Enhancement Skills VI', 'COMPUTER SCIENCE', 1, 2, 6, 0),
        ('Universal Human Values',        'COMPUTER SCIENCE', 2, 2, 6, 0),
    ]
    for s in sem6_subjects:
        c.execute("INSERT OR IGNORE INTO subject(name,department,credits,hours_per_week,semester,is_lab) VALUES(?,?,?,?,?,?)", s)

    conn.commit()
    conn.close()

# ─────────────────────────────────────────────
# Auth decorators
# ─────────────────────────────────────────────
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'admin':
            flash('Please login as Admin.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def faculty_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'faculty':
            flash('Please login as Faculty.', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ─────────────────────────────────────────────
# Auth routes
# ─────────────────────────────────────────────
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        login_type = request.form.get('login_type')
        username   = request.form.get('username', '').strip()
        password   = request.form.get('password', '').strip()
        pw_hash    = hash_password(password)

        conn = get_db()
        if login_type == 'admin':
            row = conn.execute("SELECT * FROM admin WHERE username=? AND password=?", (username, pw_hash)).fetchone()
            conn.close()
            if row:
                session.clear()
                session['role'] = 'admin'
                session['username'] = username
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Invalid admin credentials.', 'error')
        else:
            row = conn.execute("SELECT * FROM faculty WHERE email=? AND password=?", (username, pw_hash)).fetchone()
            conn.close()
            if row:
                session.clear()
                session['role']         = 'faculty'
                session['faculty_id']   = row['id']
                session['faculty_name'] = row['name']
                return redirect(url_for('faculty_dashboard'))
            else:
                flash('Invalid faculty credentials.', 'error')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('login'))

# ─────────────────────────────────────────────
# Admin routes
# ─────────────────────────────────────────────
@app.route('/admin')
@admin_required
def admin_dashboard():
    conn = get_db()
    faculty_list = conn.execute("SELECT * FROM faculty ORDER BY name").fetchall()
    subjects     = conn.execute("SELECT * FROM subject ORDER BY semester, name").fetchall()
    prefs = conn.execute("""
        SELECT fp.id, f.name AS faculty_name, s.name AS subject_name, s.is_lab, s.semester
        FROM faculty_preference fp
        JOIN faculty f ON fp.faculty_id = f.id
        JOIN subject s ON fp.subject_id = s.id
        ORDER BY f.name
    """).fetchall()
    allocations = conn.execute("""
        SELECT a.id, f.name AS faculty_name, s.name AS subject_name, s.semester,
               f.role, f.max_workload, s.hours_per_week, s.is_lab, a.batch_no
        FROM allocation a
        JOIN faculty f ON a.faculty_id = f.id
        JOIN subject s ON a.subject_id = s.id
        ORDER BY s.semester, s.name, a.batch_no, f.name
    """).fetchall()
    conn.close()
    return render_template('admin_dashboard.html',
                           faculty_list=faculty_list,
                           subjects=subjects,
                           prefs=prefs,
                           allocations=allocations,
                           workload_limits=WORKLOAD_LIMITS,
                           lab_batches=LAB_BATCHES,
                           semesters=SEMESTERS)

@app.route('/admin/faculty/add', methods=['POST'])
@admin_required
def add_faculty():
    name       = request.form['name'].strip()
    email      = request.form['email'].strip().lower()
    password   = request.form['password'].strip()
    role       = request.form['role']
    department = request.form['department'].strip().upper()
    max_wl     = WORKLOAD_LIMITS.get(role, 16)

    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO faculty(name,email,password,role,department,max_workload) VALUES(?,?,?,?,?,?)",
            (name, email, hash_password(password), role, department, max_wl)
        )
        conn.commit()
        conn.close()
        flash(f'Faculty "{name}" added successfully.', 'success')
    except sqlite3.IntegrityError:
        flash('Email already exists.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/faculty/edit/<int:fid>', methods=['POST'])
@admin_required
def edit_faculty(fid):
    name       = request.form['name'].strip()
    email      = request.form['email'].strip().lower()
    role       = request.form['role']
    department = request.form['department'].strip().upper()
    max_wl     = WORKLOAD_LIMITS.get(role, 16)
    new_pw     = request.form.get('password', '').strip()

    conn = get_db()
    if new_pw:
        conn.execute("UPDATE faculty SET name=?,email=?,role=?,department=?,max_workload=?,password=? WHERE id=?",
                    (name, email, role, department, max_wl, hash_password(new_pw), fid))
    else:
        conn.execute("UPDATE faculty SET name=?,email=?,role=?,department=?,max_workload=? WHERE id=?",
                    (name, email, role, department, max_wl, fid))
    conn.commit()
    conn.close()
    flash('Faculty updated successfully.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/faculty/delete/<int:fid>', methods=['POST'])
@admin_required
def delete_faculty(fid):
    conn = get_db()
    conn.execute("DELETE FROM faculty WHERE id=?", (fid,))
    conn.commit()
    conn.close()
    flash('Faculty deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/subject/add', methods=['POST'])
@admin_required
def add_subject():
    name       = request.form['name'].strip()
    department = request.form['department'].strip().upper()
    credits    = int(request.form['credits'])
    semester   = int(request.form['semester'])
    is_lab     = 1 if request.form.get('is_lab') else 0
    # Formula: Credits + 1 hours for theory, Credits + 1 or fixed for labs.
    # User said 3 credits -> 4 class.
    hours = credits + 1

    try:
        conn = get_db()
        conn.execute(
            "INSERT INTO subject(name,department,credits,hours_per_week,semester,is_lab) VALUES(?,?,?,?,?,?)",
            (name, department, credits, hours, semester, is_lab)
        )
        conn.commit()
        conn.close()
        flash(f'Subject "{name}" added.', 'success')
    except sqlite3.IntegrityError:
        flash('Subject already exists for this semester.', 'error')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/subject/delete/<int:sid>', methods=['POST'])
@admin_required
def delete_subject(sid):
    conn = get_db()
    conn.execute("DELETE FROM subject WHERE id=?", (sid,))
    conn.commit()
    conn.close()
    flash('Subject deleted.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/assign', methods=['POST'])
@admin_required
def assign_subjects():
    conn = get_db()
    conn.execute("DELETE FROM allocation")

    subjects = conn.execute("SELECT * FROM subject").fetchall()
    faculty_rows = conn.execute("SELECT * FROM faculty").fetchall()
    
    faculty_workload = {f['id']: 0 for f in faculty_rows}
    prefs_rows = conn.execute("SELECT faculty_id, subject_id FROM faculty_preference").fetchall()
    faculty_prefs = {}
    for p in prefs_rows:
        faculty_prefs.setdefault(p['faculty_id'], []).append(p['subject_id'])
    
    subjects = list(subjects)
    random.shuffle(subjects)

    for s in subjects:
        num_sessions = LAB_BATCHES if s['is_lab'] else 1
        sessions_assigned = 0
        
        # Filter candidates: If Semester 2, only Prof. Shilpa S can take it
        if s['semester'] == 2:
            candidates = [f for f in faculty_rows if f['name'] == 'Prof. Shilpa S']
        else:
            # Priority 1: Faculty who prefer this
            p_facs = [f for f in faculty_rows if s['id'] in faculty_prefs.get(f['id'], [])]
            random.shuffle(p_facs)
            
            # Priority 2: All other faculty
            all_facs = list(faculty_rows)
            random.shuffle(all_facs)
            candidates = p_facs + [f for f in all_facs if f not in p_facs]

        for f in candidates:
            if sessions_assigned >= num_sessions: break
            
            hw = s['hours_per_week']
            if faculty_workload[f['id']] + hw <= f['max_workload']:
                batch_no = (sessions_assigned + 1) if s['is_lab'] else None
                conn.execute("INSERT INTO allocation(faculty_id, subject_id, batch_no) VALUES(?,?,?)",
                            (f['id'], s['id'], batch_no))
                faculty_workload[f['id']] += hw
                sessions_assigned += 1

    conn.commit()
    conn.close()
    flash('Subject assignment complete.', 'success')
    return redirect(url_for('admin_dashboard'))

@app.route('/admin/timetable/generate', methods=['POST'])
@admin_required
def generate_timetable():
    conn = get_db()
    conn.execute("DELETE FROM timetable")

    # 1. Fixed Slots
    fixed_rows = conn.execute("SELECT * FROM fixed_schedule").fetchall()
    for r in fixed_rows:
        conn.execute("INSERT INTO timetable(day,period_id,semester,batch_no,is_fixed) VALUES(?,?,?,0,1)", 
                    (r['day'], r['period_id'], r['semester']))

    # 2. Allocations
    allocations = conn.execute("""
        SELECT a.faculty_id, a.subject_id, a.batch_no, s.semester, s.hours_per_week, s.is_lab, s.name as sname
        FROM allocation a JOIN subject s ON a.subject_id = s.id
    """).fetchall()

    # Tracking
    # (day, period_id, semester) -> occupied
    sem_occupied = {}
    # (day, period_id, faculty_id) -> occupied
    fac_occupied = {}

    # Group lab batches by (semester, subject_id) for parallel scheduling
    lab_allocs = [a for a in allocations if a['is_lab']]
    lab_groups = {}
    for a in lab_allocs:
        key = (a['semester'], a['subject_id'])
        lab_groups.setdefault(key, []).append(a)

    for (sem, sid), group in lab_groups.items():
        # group is a list of allocations (fid, sid, batch, sem)
        days = list(DAYS)
        random.shuffle(days)
        placed = False
        for day in days:
            max_p = SATURDAY_MAX_PERIOD_ID if day == 'Saturday' else 8
            # Look for pairs (p1, p2) in TEACHING_PERIOD_IDS
            pairs = []
            for i in range(len(TEACHING_PERIOD_IDS)-1):
                p1 = TEACHING_PERIOD_IDS[i]; p2 = TEACHING_PERIOD_IDS[i+1]
                if p1 <= max_p and p2 <= max_p and p2 == p1 + 1:
                    pairs.append((p1, p2))
            random.shuffle(pairs)
            
            for p1, p2 in pairs:
                # Check semantic clash for this semester (slot must be completely free)
                if not conn.execute("SELECT 1 FROM timetable WHERE day=? AND semester=? AND period_id IN (?,?)", (day, sem, p1, p2)).fetchone():
                    # Check for individual faculty clashes across semesters
                    clash = False
                    for alloc in group:
                        if conn.execute("SELECT 1 FROM timetable WHERE day=? AND faculty_id=? AND period_id IN (?,?)", (day, alloc['faculty_id'], p1, p2)).fetchone():
                            clash = True; break
                    if not clash:
                        # Schedule all batches in this slot
                        for alloc in group:
                            conn.execute("INSERT INTO timetable(day,period_id,semester,faculty_id,subject_id,batch_no) VALUES(?,?,?,?,?,?)",
                                        (day, p1, sem, alloc['faculty_id'], sid, alloc['batch_no']))
                            conn.execute("INSERT INTO timetable(day,period_id,semester,faculty_id,subject_id,batch_no) VALUES(?,?,?,?,?,?)",
                                        (day, p2, sem, alloc['faculty_id'], sid, alloc['batch_no']))
                        placed = True; break
            if placed: break

    # Schedule Theory
    theory_allocs = [a for a in allocations if not a['is_lab']]
    random.shuffle(theory_allocs)

    for alloc in theory_allocs:
        fid = alloc['faculty_id']
        sid = alloc['subject_id']
        sem = alloc['semester']
        hours = alloc['hours_per_week']
        
        assigned_hours = 0
        days = list(DAYS) * 2
        random.shuffle(days)
        for day in days:
            if assigned_hours >= hours: break
            max_p = SATURDAY_MAX_PERIOD_ID if day == 'Saturday' else 8
            periods = [p for p in TEACHING_PERIOD_IDS if p <= max_p]
            random.shuffle(periods)
            for p in periods:
                # Check semester occupied
                if not conn.execute("SELECT 1 FROM timetable WHERE day=? AND semester=? AND period_id=?", (day, sem, p)).fetchone():
                    # Check faculty occupied
                    if not conn.execute("SELECT 1 FROM timetable WHERE day=? AND faculty_id=? AND period_id=?", (day, fid, p)).fetchone():
                        conn.execute("INSERT INTO timetable(day,period_id,semester,faculty_id,subject_id,batch_no) VALUES(?,?,?,?,?,0)", (day, p, sem, fid, sid))
                        assigned_hours += 1
                        break

    conn.commit()
    conn.close()
    flash('Timetable generated for all semesters!', 'success')
    return redirect(url_for('view_timetable'))

@app.route('/admin/timetable')
@admin_required
def view_timetable():
    sem = request.args.get('semester', 2, type=int)
    conn = get_db()
    rows = conn.execute("""
        SELECT t.day, t.period_id, t.semester, t.is_fixed, t.batch_no,
               f.name AS faculty_name, s.name AS subject_name, s.is_lab
        FROM timetable t
        LEFT JOIN faculty f ON t.faculty_id = f.id
        LEFT JOIN subject s ON t.subject_id = s.id
        WHERE t.semester = ?
    """, (sem,)).fetchall()

    lab_bmap = {}
    for lb in conn.execute("""
        SELECT a.subject_id, a.batch_no, f.name AS faculty_name
        FROM allocation a JOIN faculty f ON a.faculty_id = f.id
        WHERE a.batch_no IS NOT NULL
    """).fetchall():
        lab_bmap.setdefault(lb['subject_id'], []).append({'batch_no': lb['batch_no'], 'faculty_name': lb['faculty_name']})

    fixed_rows = conn.execute("SELECT * FROM fixed_schedule WHERE semester=?", (sem,)).fetchall()
    conn.close()

    fixed_map = {(r['day'], r['period_id']): r['subject_name'] for r in fixed_rows}
    grid = {d: {p['id']: [] for p in PERIODS} for d in DAYS}
    for r in rows:
        grid[r['day']][r['period_id']].append(dict(r))

    # Saturday periods filtered
    return render_template('timetable.html',
                           grid=grid, periods=PERIODS, days=DAYS,
                           fixed_map=fixed_map, is_admin=True,
                           lab_bmap=lab_bmap, current_sem=sem, semesters=SEMESTERS,
                           sat_max=SATURDAY_MAX_PERIOD_ID)

# ─────────────────────────────────────────────
# Faculty routes
# ─────────────────────────────────────────────
@app.route('/faculty')
@faculty_required
def faculty_dashboard():
    fid  = session['faculty_id']
    conn = get_db()
    faculty  = conn.execute("SELECT * FROM faculty WHERE id=?", (fid,)).fetchone()
    subjects = conn.execute("SELECT * FROM subject ORDER BY semester, name").fetchall()
    prefs    = conn.execute("SELECT subject_id FROM faculty_preference WHERE faculty_id=?", (fid,)).fetchall()
    pref_ids = [p['subject_id'] for p in prefs]

    # Faculty can have multiple allocations now
    allocations = conn.execute("""
        SELECT s.name AS subject_name, s.hours_per_week, s.is_lab, a.batch_no, s.semester
        FROM allocation a JOIN subject s ON a.subject_id = s.id
        WHERE a.faculty_id=?
    """, (fid,)).fetchall()
    conn.close()

    return render_template('faculty_dashboard.html',
                           faculty=faculty, subjects=subjects,
                           pref_ids=pref_ids, allocations=allocations,
                           workload_limits=WORKLOAD_LIMITS,
                           lab_batches=LAB_BATCHES)

@app.route('/faculty/preferences', methods=['POST'])
@faculty_required
def submit_preferences():
    fid  = session['faculty_id']
    sids = request.form.getlist('subjects')
    if len(sids) != 2:
        flash('Please select exactly 2 subjects.', 'error')
        return redirect(url_for('faculty_dashboard'))

    conn = get_db()
    conn.execute("DELETE FROM faculty_preference WHERE faculty_id=?", (fid,))
    for sid in sids:
        conn.execute("INSERT OR IGNORE INTO faculty_preference(faculty_id,subject_id) VALUES(?,?)", (fid, int(sid)))
    conn.commit()
    conn.close()
    flash('Preferences saved!', 'success')
    return redirect(url_for('faculty_dashboard'))

@app.route('/faculty/timetable')
@faculty_required
def faculty_timetable():
    fid  = session['faculty_id']
    conn = get_db()
    
    # Faculty view: show their assigned slots across all semesters
    rows = conn.execute("""
        SELECT t.day, t.period_id, t.semester, t.is_fixed, t.batch_no,
               f.name AS faculty_name, s.name AS subject_name, s.is_lab
        FROM timetable t
        LEFT JOIN faculty f ON t.faculty_id = f.id
        LEFT JOIN subject s ON t.subject_id = s.id
        WHERE t.faculty_id = ? OR t.is_fixed = 1
    """, (fid,)).fetchall()
    conn.close()

    grid = {d: {p['id']: [] for p in PERIODS} for d in DAYS}
    for r in rows:
        grid[r['day']][r['period_id']].append(dict(r))

    return render_template('timetable.html',
                           grid=grid, periods=PERIODS, days=DAYS,
                           fixed_map={}, is_admin=False,
                           lab_bmap={}, semesters=SEMESTERS,
                           sat_max=SATURDAY_MAX_PERIOD_ID)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
