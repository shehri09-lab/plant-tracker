import streamlit as st
import pandas as pd
import os
import socket
import io
import zipfile
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
from sqlalchemy.sql import func
import google.generativeai as genai

# --- NEW IMPORTS FOR QR ---
import qrcode
from PIL import Image, ImageDraw, ImageFont

# --- CONFIGURATION ---
DB_FILE = "plant_v3.db"
ASSETS_DIR = "assets"
if not os.path.exists(ASSETS_DIR): os.makedirs(ASSETS_DIR)

# --- DATABASE MODELS ---
Base = declarative_base()

class Settings(Base):
    __tablename__ = 'settings'
    id = Column(Integer, primary_key=True)
    company_name = Column(String, default="Al-Yamama Engineering")
    operator_name = Column(String, default="Shehryar Ali")
    banner_path = Column(String, nullable=True)
    logo_path = Column(String, nullable=True)
    operator_photo_path = Column(String, nullable=True)
    plant_video_path = Column(String, nullable=True)
    ai_api_key = Column(String, nullable=True)

class Person(Base):
    __tablename__ = 'people'
    id = Column(Integer, primary_key=True)
    name = Column(String)
    designation = Column(String) 
    phone = Column(String)
    whatsapp = Column(String)
    photo_path = Column(String)
    notes = Column(Text)
    trips = relationship("Trip", back_populates="driver", cascade="all, delete-orphan")
    overtimes = relationship("Overtime", back_populates="worker", cascade="all, delete-orphan")

class Trip(Base):
    __tablename__ = 'trips'
    id = Column(Integer, primary_key=True)
    driver_id = Column(Integer, ForeignKey('people.id'))
    date = Column(DateTime, default=datetime.now)
    trip_count = Column(Integer, default=1)
    driver = relationship("Person", back_populates="trips")

class Overtime(Base):
    __tablename__ = 'overtime'
    id = Column(Integer, primary_key=True)
    worker_id = Column(Integer, ForeignKey('people.id'))
    date = Column(DateTime, default=datetime.now)
    hours = Column(Float)
    reason = Column(String)
    worker = relationship("Person", back_populates="overtimes")

class ConcreteRecord(Base):
    __tablename__ = 'concrete'
    id = Column(Integer, primary_key=True)
    date = Column(DateTime, default=datetime.now)
    site_name = Column(String)
    grade = Column(String)
    quantity = Column(Float)
    notes = Column(String)

# --- DB INIT ---
engine = create_engine(f"sqlite:///{DB_FILE}", connect_args={"check_same_thread": False})
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)
db = SessionLocal()

# --- PAGE CONFIG ---
st.set_page_config(page_title="Al-Yamama Engineering", layout="wide", page_icon="🏗️")

# --- UTILS ---
def get_detailed_history(person_id):
    """Fetches combined trips and overtime data sorted by date."""
    trips = db.query(Trip).filter(Trip.driver_id == person_id).all()
    ots = db.query(Overtime).filter(Overtime.worker_id == person_id).all()
    
    combined = {}
    for t in trips:
        d_str = t.date.strftime("%Y-%m-%d")
        combined.setdefault(d_str, {"Date": d_str, "Trips": 0, "OT Hours": 0.0})
        combined[d_str]["Trips"] += t.trip_count
        
    for o in ots:
        d_str = o.date.strftime("%Y-%m-%d")
        combined.setdefault(d_str, {"Date": d_str, "Trips": 0, "OT Hours": 0.0})
        combined[d_str]["OT Hours"] += o.hours
        
    return sorted(list(combined.values()), key=lambda x: x["Date"], reverse=True)

# ==========================================
# --- PUBLIC QR VIEW INTERCEPTOR ---
# ==========================================
if "worker_id" in st.query_params:
    worker_id = st.query_params["worker_id"]
    p = db.query(Person).filter(Person.id == worker_id).first()
    
    if p:
        st.markdown(f"<h1 style='text-align:center;'>👷 {p.name}</h1>", unsafe_allow_html=True)
        st.markdown(f"<h3 style='text-align:center; color:gray;'>{p.designation}</h3>", unsafe_allow_html=True)
        st.divider()
        
        history = get_detailed_history(p.id)
        t_trips = sum(item["Trips"] for item in history)
        t_ot = sum(item["OT Hours"] for item in history)
        
        c1, c2 = st.columns(2)
        c1.metric("🚛 Total Trips", t_trips)
        c2.metric("⏱️ Total Overtime (Hrs)", t_ot)
        
        st.subheader("📅 Work History (By Date)")
        st.table(history)
        st.info("✅ This is your live work record. Scanned via Office QR.")
    else:
        st.error("Worker record not found.")
    st.stop()

# --- UTILS ---
def save_file(uploaded_file):
    if uploaded_file is None: return None
    path = os.path.join(ASSETS_DIR, uploaded_file.name)
    with open(path, "wb") as f: f.write(uploaded_file.getbuffer())
    return path

def get_settings():
    s = db.query(Settings).first()
    if not s:
        s = Settings()
        db.add(s)
        db.commit()
    return s

def delete_person(person_id):
    p = db.query(Person).get(person_id)
    if p:
        db.delete(p)
        db.commit()
        return True
    return False

def generate_excel(data, filename, sheet_name):
    df = pd.DataFrame(data)
    if not df.empty and '_sa_instance_state' in df.columns:
        del df['_sa_instance_state']
    path = f"{filename}.xlsx"
    writer = pd.ExcelWriter(path, engine='xlsxwriter')
    df.to_excel(writer, sheet_name=sheet_name, index=False)
    writer.close()
    return path

def create_worker_card(p, base_url):
    img = Image.new('RGB', (600, 250), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    qr_url = f"{base_url}?worker_id={p.id}"
    qr = qrcode.make(qr_url).resize((200, 200))
    img.paste(qr, (380, 25))
    if p.photo_path and os.path.exists(p.photo_path):
        try:
            pic = Image.open(p.photo_path).resize((150, 150))
            img.paste(pic, (30, 50))
        except: pass
    draw.text((200, 80), f"Name: {p.name}", fill=(0, 0, 0))
    draw.text((200, 110), f"Role: {p.designation}", fill=(100, 100, 100))
    draw.text((200, 150), "Scan QR with phone", fill=(31, 119, 180))
    draw.text((200, 170), "to view your trips & OT", fill=(31, 119, 180))
    draw.rectangle([0, 0, 599, 249], outline=(0, 210, 255), width=4)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

settings = get_settings()

if "theme" not in st.session_state: st.session_state.theme = "dark"
def toggle_theme(): st.session_state.theme = "light" if st.session_state.theme == "dark" else "dark"

if st.session_state.theme == "dark":
    st.markdown("""<style>.stApp { background-color: #0e1117; color: #ffffff; }
    .neon-header { font-family: 'Arial Black', sans-serif; font-size: 40px; color: #ffffff; text-shadow: 0 0 10px #0ff; }
    div[data-testid="stMetric"], div[data-testid="stForm"] { background-color: #1a1d24; border: 1px solid #333; border-radius: 15px; padding: 15px; box-shadow: 0 0 10px #00d2ff; }
    section[data-testid="stSidebar"] { background-color: #111; border-right: 2px solid #00d2ff; }
    h1, h2, h3 { color: #00d2ff !important; }
    .stat-box { background-color: #333; padding: 5px; border-radius: 5px; margin-top: 5px; font-size: 12px; text-align: center; }
    </style>""", unsafe_allow_html=True)
else:
    st.markdown("""<style>.stApp { background-color: #ffffff; color: #000000; }
    .neon-header { font-family: 'Arial Black', sans-serif; font-size: 40px; color: #1f77b4; }
    div[data-testid="stMetric"], div[data-testid="stForm"] { background-color: #f0f2f6; border: 1px solid #ccc; border-radius: 15px; padding: 15px; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }
    section[data-testid="stSidebar"] { background-color: #f8f9fa; border-right: 1px solid #ddd; }
    h1, h2, h3 { color: #1f77b4 !important; }
    .stat-box { background-color: #eee; padding: 5px; border-radius: 5px; margin-top: 5px; font-size: 12px; text-align: center; }
    </style>""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown(f"<h2 style='text-align:center;'>{settings.company_name}</h2>", unsafe_allow_html=True)
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        if settings.logo_path and os.path.exists(settings.logo_path): st.image(settings.logo_path, width=120)
        if settings.operator_photo_path and os.path.exists(settings.operator_photo_path): st.image(settings.operator_photo_path, caption=settings.operator_name, width=120)
    if st.button("Switch Theme"): toggle_theme(); st.rerun()
    st.divider()
    menu = st.radio("NAVIGATION", ["🏠 HOME", "👥 TEAM & TRIPS", "🏗️ CONCRETE DATA", "📊 EXPORT", "⚙️ SETTINGS", "🤖 REAL AI BOT"])

if menu == "🏠 HOME":
    if settings.banner_path and os.path.exists(settings.banner_path): st.image(settings.banner_path, use_container_width=True)
    st.markdown(f"<div class='neon-header'>AL-YAMAMA ENGINEERING</div>", unsafe_allow_html=True)
    st.write(f"### Welcome, Engineer {settings.operator_name}")
    today = datetime.now().date()
    conc_today = db.query(func.sum(ConcreteRecord.quantity)).filter(func.date(ConcreteRecord.date) == today).scalar() or 0
    trips_today = db.query(func.sum(Trip.trip_count)).filter(func.date(Trip.date) == today).scalar() or 0
    active_drivers = db.query(Person).filter(Person.designation.ilike("%Driver%")).count()
    c1, c2, c3 = st.columns(3)
    c1.metric("Concrete Today (m3)", f"{conc_today}")
    c2.metric("Trips Today", trips_today)
    c3.metric("Drivers Available", active_drivers)

elif menu == "👥 TEAM & TRIPS":
    st.markdown("<h2>STAFF MANAGEMENT</h2>", unsafe_allow_html=True)
    tab1, tab2, tab3 = st.tabs(["👥 CARDS VIEW", "📝 ADD & FULL LIST", "🖨️ QR PRINT CARDS"])
    
    with tab1:
        st.subheader("Team Cards")
        staff = db.query(Person).all()
        for i in range(0, len(staff), 4):
            cols = st.columns(4)
            for j, col in enumerate(cols):
                if i + j < len(staff):
                    p = staff[i+j]
                    with col:
                        with st.container(border=True):
                            # --- CLICK PHOTO TO SEE DETAIL ---
                            if p.photo_path and os.path.exists(p.photo_path):
                                if st.button("👁️ View Details", key=f"v_{p.id}"):
                                    st.session_state.view_worker = p.id
                                st.image(p.photo_path, width=80)
                            else: st.write("👤 No Photo")
                            
                            st.write(f"**{p.name}**")
                            st.caption(f"{p.designation}")
                            
                            total_trips = db.query(func.sum(Trip.trip_count)).filter(Trip.driver_id == p.id).scalar() or 0
                            total_ot = db.query(func.sum(Overtime.hours)).filter(Overtime.worker_id == p.id).scalar() or 0
                            st.markdown(f"<div class='stat-box'>🚛 Trips: {total_trips} <br> ⏱️ OT: {total_ot} hrs</div>", unsafe_allow_html=True)
                            
                            if st.button("🗑️ Delete", key=f"del_{p.id}"): delete_person(p.id); st.rerun()

        # --- DETAILED MODAL VIEW ---
        if "view_worker" in st.session_state:
            p_detail = db.query(Person).get(st.session_state.view_worker)
            if p_detail:
                st.divider()
                st.markdown(f"### 📊 Detailed Record: {p_detail.name}")
                history = get_detailed_history(p_detail.id)
                
                # Search by Date
                search_date = st.text_input("🔍 Search by Date (YYYY-MM-DD)", "")
                if search_date:
                    history = [h for h in history if search_date in h["Date"]]
                
                # Professional Metrics on Top
                total_t = sum(h["Trips"] for h in history)
                total_h = sum(h["OT Hours"] for h in history)
                m1, m2 = st.columns(2)
                m1.metric("Big Total Trips", total_t)
                m2.metric("Big Total Hours", total_h)
                
                st.dataframe(history, use_container_width=True, hide_index=True)
                if st.button("❌ Close Sheet"):
                    del st.session_state.view_worker
                    st.rerun()

    with tab2:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("### ➕ Add New Person")
            with st.form("add_staff"):
                name = st.text_input("Name")
                role = st.text_input("Designation")
                phone = st.text_input("Phone")
                wa = st.text_input("WhatsApp Number")
                pic = st.file_uploader("Photo", type=['jpg','png'])
                if st.form_submit_button("Add Person"):
                    path = save_file(pic)
                    db.add(Person(name=name, designation=role, phone=phone, whatsapp=wa, photo_path=path))
                    db.commit(); st.success("Added!"); st.rerun()
        with c2:
            st.markdown("### 📝 Log Work")
            p_list = {p.name: p for p in staff}
            target = st.selectbox("Select Person", list(p_list.keys()) if p_list else [])
            if target:
                p = p_list[target]
                t_tab, o_tab = st.tabs(["🚛 TRIPS", "⏱️ OVERTIME"])
                with t_tab:
                    with st.form("add_trip"):
                        d_date = st.date_input("Select Date", key="t_date")
                        d_count = st.number_input("Number of Trips", min_value=1, value=1)
                        if st.form_submit_button("Save Trip"):
                            db.add(Trip(driver_id=p.id, date=d_date, trip_count=d_count))
                            db.commit(); st.success("Logged!"); st.rerun()
                with o_tab:
                    with st.form("add_ot_d"):
                        o_date = st.date_input("Select Date", key="o_date_d")
                        o_hrs = st.number_input("Overtime Hours", min_value=0.5, step=0.5)
                        if st.form_submit_button("Save OT"):
                            db.add(Overtime(worker_id=p.id, date=o_date, hours=o_hrs, reason="Standard"))
                            db.commit(); st.success("Logged!"); st.rerun()

    with tab3:
        st.markdown("### 🖨️ Office Print Center")
        try:
            local_ip = socket.gethostbyname(socket.gethostname())
            default_url = f"http://{local_ip}:8501"
        except: default_url = "http://localhost:8501"
        base_url = st.text_input("App Network URL:", value=default_url)
        if st.button("📦 Download ALL ZIP"):
            zip_buf = io.BytesIO()
            with zipfile.ZipFile(zip_buf, "w") as zf:
                for p in staff:
                    card_bytes = create_worker_card(p, base_url)
                    zf.writestr(f"{p.name}_QR_Card.png", card_bytes)
            st.download_button("📥 Click to Save ZIP", zip_buf.getvalue(), "Team_QR_Cards.zip", "application/zip")
        
        st.divider()
        cols = st.columns(3)
        for i, p in enumerate(staff):
            with cols[i % 3]:
                card_bytes = create_worker_card(p, base_url)
                st.image(card_bytes, use_container_width=True)
                st.download_button(f"Download {p.name}", card_bytes, f"{p.name}_QR.png", "image/png", key=f"dl_qr_{p.id}")

elif menu == "🏗️ CONCRETE DATA":
    st.markdown("<h2>CONCRETE PRODUCTION</h2>", unsafe_allow_html=True)
    with st.expander("➕ ADD RECORD", expanded=True):
        with st.form("conc_form"):
            c1, c2, c3, c4 = st.columns(4)
            d = c1.date_input("Date")
            site = c2.text_input("Site Name")
            grade = c3.selectbox("Grade", ["C10", "C20", "C30", "C35", "C40", "C50", "Blinding"])
            qty = c4.number_input("Quantity (m3)")
            if st.form_submit_button("SAVE RECORD"):
                db.add(ConcreteRecord(date=d, site_name=site, grade=grade, quantity=qty))
                db.commit(); st.success("Saved!"); st.rerun()
    st.divider()
    m = st.selectbox("Select Month", range(1, 13), index=datetime.now().month-1)
    records = db.query(ConcreteRecord).filter(func.extract('month', ConcreteRecord.date) == m).all()
    rec_data = [{"ID": r.id, "Date": r.date.date(), "Site": r.site_name, "Grade": r.grade, "Quantity": r.quantity} for r in records]
    st.data_editor(rec_data, num_rows="dynamic", use_container_width=True, key="conc_edit")

elif menu == "📊 EXPORT":
    st.title("Reports Center")
    people = db.query(Person).all()
    target = st.selectbox("Select Person", [p.name for p in people])
    if st.button("Generate Excel"):
        p = db.query(Person).filter_by(name=target).first()
        history = get_detailed_history(p.id)
        fname = generate_excel(history, f"{p.name}_Full_Report", "Records")
        with open(fname, "rb") as f: st.download_button("Download", f, file_name=fname)

elif menu == "⚙️ SETTINGS":
    st.title("Settings")
    key_input = st.text_input("AI API Key", value=settings.ai_api_key if settings.ai_api_key else "", type="password")
    if st.button("SAVE KEY"): settings.ai_api_key = key_input; db.commit(); st.success("Saved!")
    with st.form("sets"):
        comp = st.text_input("Company", settings.company_name)
        op = st.text_input("Operator", settings.operator_name)
        ban = st.file_uploader("Banner", type=['jpg','png'])
        log = st.file_uploader("Logo", type=['jpg','png'])
        if st.form_submit_button("SAVE VISUALS"):
            settings.company_name = comp
            settings.operator_name = op
            if ban: settings.banner_path = save_file(ban)
            if log: settings.logo_path = save_file(log)
            db.commit(); st.rerun()

elif menu == "🤖 REAL AI BOT":
    st.title("Plant AI")
    if not settings.ai_api_key: st.warning("Please add API Key in Settings")
    else:
        genai.configure(api_key=settings.ai_api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
        if "chat_history" not in st.session_state: st.session_state.chat_history = []
        for role, text in st.session_state.chat_history:
            with st.chat_message(role): st.write(text)
        if prompt := st.chat_input("Ask AI..."):
            st.session_state.chat_history.append(("user", prompt))
            with st.chat_message("user"): st.write(prompt)
            conc_sum = db.query(func.sum(ConcreteRecord.quantity)).scalar() or 0
            try:
                response = model.generate_content(f"Context: Plant {settings.company_name}, Concrete={conc_sum}. Question: {prompt}")
                bot_reply = response.text
            except: bot_reply = "AI Error."
            st.session_state.chat_history.append(("assistant", bot_reply))
            with st.chat_message("assistant"): st.write(bot_reply)