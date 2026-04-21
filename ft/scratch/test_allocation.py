import sqlite3
import random

DATABASE = 'faculty_system.db'
WORKLOAD_LIMITS = {'HOD': 8, 'Professor': 12, 'Assistant Professor': 16}
LAB_BATCHES = 4

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def test_allocation_logic():
    print("--- Testing Balanced Allocation Logic ---")
    conn = get_db()
    
    # Reset allocations for testing
    conn.execute("DELETE FROM allocation")
    
    subjects_all = conn.execute("SELECT * FROM subject").fetchall()
    faculty_rows = conn.execute("SELECT * FROM faculty").fetchall()
    
    faculty_workload = {f['id']: 0 for f in faculty_rows}
    faculty_theory_count = {f['id']: 0 for f in faculty_rows}
    faculty_lab_count = {f['id']: 0 for f in faculty_rows}

    theory_subs = [s for s in subjects_all if not s['is_lab']]
    lab_subs    = [s for s in subjects_all if s['is_lab']]
    
    random.shuffle(theory_subs)
    random.shuffle(lab_subs)

    # 1. Primary Theory
    for s in theory_subs[:]:
        hw = s['hours_per_week']
        candidates = sorted(faculty_rows, key=lambda f: faculty_theory_count[f['id']])
        assigned = False
        for f in candidates:
            if faculty_workload[f['id']] + hw <= f['max_workload']:
                if s['semester'] == 2 and f['name'] != 'Prof. Shilpa S': continue
                conn.execute("INSERT INTO allocation(faculty_id, subject_id, batch_no) VALUES(?,?,?)", (f['id'], s['id'], None))
                faculty_workload[f['id']] += hw
                faculty_theory_count[f['id']] += 1
                theory_subs.remove(s)
                assigned = True
                break
        if assigned: continue

    # 2. Labs (Max 2 batches per person)
    MAX_BATCHES_PER_FACULTY = 2
    for s in lab_subs:
        num_sessions = LAB_BATCHES
        sessions_assigned = 0
        hw = s['hours_per_week']
        candidates = list(faculty_rows)
        random.shuffle(candidates)
        candidates.sort(key=lambda f: faculty_workload[f['id']])
        for f in candidates:
            if sessions_assigned >= num_sessions: break
            existing_batches = 0
            while sessions_assigned < num_sessions and existing_batches < MAX_BATCHES_PER_FACULTY:
                if faculty_workload[f['id']] + hw <= f['max_workload']:
                    conn.execute("INSERT INTO allocation(faculty_id, subject_id, batch_no) VALUES(?,?,?)", (f['id'], s['id'], sessions_assigned+1))
                    faculty_workload[f['id']] += hw
                    faculty_lab_count[f['id']] += 1
                    sessions_assigned += 1
                    existing_batches += 1
                else: break

    # 3. Remaining Theory
    for s in theory_subs:
        hw = s['hours_per_week']
        candidates = sorted(faculty_rows, key=lambda f: (faculty_workload[f['id']], faculty_theory_count[f['id']]))
        for f in candidates:
            if faculty_workload[f['id']] + hw <= f['max_workload']:
                if s['semester'] == 2 and f['name'] != 'Prof. Shilpa S': continue
                conn.execute("INSERT INTO allocation(faculty_id, subject_id, batch_no) VALUES(?,?,?)", (f['id'], s['id'], None))
                faculty_workload[f['id']] += hw
                faculty_theory_count[f['id']] += 1
                break

    conn.commit()
    
    # Results analysis
    print("\nAllocation Results:")
    rows = conn.execute("""
        SELECT f.name, COUNT(DISTINCT CASE WHEN s.is_lab=0 THEN a.subject_id END) as theory_count,
               COUNT(DISTINCT CASE WHEN s.is_lab=1 THEN a.subject_id END) as lab_subject_count,
               COUNT(a.batch_no) as lab_batch_count
        FROM faculty f
        LEFT JOIN allocation a ON f.id = a.faculty_id
        LEFT JOIN subject s ON a.subject_id = s.id
        GROUP BY f.id
    """).fetchall()
    
    for r in rows:
        print(f"Faculty: {r['name']:<25} | Theory: {r['theory_count']} | Labs: {r['lab_subject_count']} ({r['lab_batch_count']} batches)")
        if r['theory_count'] > 0 and r['lab_batch_count'] > 0:
            print("  [OK] Mixed Load")
        elif r['theory_count'] > 0:
            print("  [INFO] Theory Only")
        else:
            print("  [WARN] Unbalanced")

    conn.close()

if __name__ == "__main__":
    test_allocation_logic()
