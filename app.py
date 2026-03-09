import streamlit as st
import pandas as pd
import os
import socket
import io
import zipfile
import urllib.parse  # Required for WhatsApp links
from datetime import datetime
from sqlalchemy import create_engine, Column, Integer, String, DateTime, Float, ForeignKey, Text
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
from sqlalchemy.sql import func
import google.generativeai as genai

# --- NEW IMPORTS ---
import qrcode
from PIL import Image, ImageDraw, ImageFont
from fpdf import FPDF

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

# --- PDF & QR GENERATION ---
def create_worker_card(p, base_url):
    img = Image.new('RGB', (600, 300), color=(255, 255, 255))
    draw = ImageDraw.Draw(img)
    qr_url = f"{base_url}?worker_id={p.id}"
    qr = qrcode.make(qr_url).resize((220, 220))
    img.paste(qr, (350, 40))
    if p.photo_path and os.path.exists(p.photo_path):
        try:
            pic = Image.open(p.photo_path).resize((180, 180))
            img.paste(pic, (30, 40))
        except: pass
    draw.text((30, 230), f"NAME: {p.name.upper()}", fill=(0, 0, 0))
    draw.text((30, 255), f"ROLE: {p.designation.upper()}", fill=(100, 100, 100))
    draw.rectangle([0, 0, 599, 299], outline=(0, 210, 255), width=6)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()

def create_joint_pdf(staff, base_url):
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=10)
    pdf.add_page()
    pdf.set_font("Arial", 'B', 16)
    pdf.set_text_color(0, 150, 200)
    pdf.cell(190, 15, txt="AL-YAMAMA ENGINEERING STAFF CODES", ln=True, align='C')
    pdf.ln(5)
    
    x_start, y_start = 10, 30
    card_w, card_h = 90, 55
    for i, p in enumerate(staff):
        col, row = i % 2, (i // 2) % 4
        if i > 0 and i % 8 == 0:
            pdf.add_page()
            y_start = 20
        x, y = x_start + (col * (card_w + 5)), y_start + (row * (card_h + 5))
        pdf.set_fill_color(245, 250, 255)
        pdf.rect(x, y, card_w, card_h, 'DF')
        pdf.set_draw_color(0, 210, 255)
        pdf.rect(x, y, card_w, card_h)
        if p.photo_path and os.path.exists(p.photo_path):
            pdf.image(p.photo_path, x + 2, y + 2, 28, 28)
        qr_url = f"{base_url}?worker_id={p.id}"
        qr_img = qrcode.make(qr_url)
        temp_qr = f"temp_{p.id}.png"
        qr_img.save(temp_qr)
        pdf.image(temp_qr, x + 58, y + 2, 30, 30)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font("Arial", 'B', 10)
        pdf.set_xy(x + 2, y + 35); pdf.cell(40, 5, p.name[:20].upper())
        pdf.set_font("Arial", '', 8)
        pdf.set_text_color(100, 100, 100)
        pdf.set_xy(x + 2, y + 42); pdf.cell(40, 5, p.designation[:25])
        if os.path.exists(temp_qr): os.remove(temp_qr)
    
    return bytes(pdf.output(dest='S'))

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
        c1, c2 = st.columns(2)
        c1.metric("🚛 Total Trips", sum(item["Trips"] for item in history))
        c2.metric("⏱️ Total Overtime (Hrs)", sum(item["OT Hours"] for item in history))
        st.subheader("📅 Work History")
        st.table(history)
    else: st.error("Worker record not found.")
    st.stop()

# --- THEME & UI ---
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
    tab1, tab2, tab3 = st.tabs(["👥 CARDS VIEW", "📝 ADD/EDIT WORKERS", "🖨️ QR PRINT CARDS"])
    staff = db.query(Person).all()
    
    with tab1:
        for i in range(0, len(staff), 4):
            cols = st.columns(4)
            for j, col in enumerate(cols):
                if i + j < len(staff):
                    p = staff[i+j]
                    with col:
                        with st.container(border=True):
                            if p.photo_path and os.path.exists(p.photo_path):
                                st.image(p.photo_path, width=80)
                            else: st.write("👤 No Photo")
                            st.write(f"**{p.name}**")
                            st.caption(f"{p.designation}")
                            t_trips = db.query(func.sum(Trip.trip_count)).filter(Trip.driver_id == p.id).scalar() or 0
                            t_ot = db.query(func.sum(Overtime.hours)).filter(Overtime.worker_id == p.id).scalar() or 0
                            st.markdown(f"<div class='stat-box'>🚛 Trips: {t_trips} | ⏱️ OT: {t_ot}</div>", unsafe_allow_html=True)
                            
                            b1, b2, b3 = st.columns(3)
                            if b1.button("👁️", key=f"v_{p.id}", help="View Details"): st.session_state.view_worker = p.id
                            if b2.button("✏️", key=f"ed_{p.id}", help="Edit Worker"): st.session_state.edit_worker = p.id
                            if b3.button("🗑️", key=f"del_{p.id}", help="Delete"): delete_person(p.id); st.rerun()

        if "view_worker" in st.session_state:
            p_detail = db.query(Person).get(st.session_state.view_worker)
            if p_detail:
                st.divider()
                st.markdown(f"### 📊 Detailed Record: {p_detail.name}")
                history = get_detailed_history(p_detail.id)
                
                # --- UPDATED: WHATSAPP REPORT BUTTON ---
                if history and p_detail.whatsapp:
                    latest = history[0]
                    # Create English & Arabic message
                    wa_msg = (
                        f"🏗️ *AL-YAMAMA ENGINEERING REPORT*\n\n"
                        f"Hello *{p_detail.name}*,\n"
                        f"The last day Date {latest['Date']} you have {latest['Trips']} trips and {latest['OT Hours']} hours. Thank you.\n"
                        f"Sincerely, {settings.operator_name}.\n\n"
                        f"مرحباً *{p_detail.name}*،\n"
                        f"في تاريخ {latest['Date']} كان لديك {latest['Trips']} رحلات و {latest['OT Hours']} ساعات عمل إضافية. شكراً لك.\n"
                        f"مع خالص التحيات، {settings.operator_name}."
                    )
                    encoded_wa = urllib.parse.quote(wa_msg)
                    wa_url = f"https://wa.me/{p_detail.whatsapp}?text={encoded_wa}"
                    st.link_button(f"🟢 SEND REPORT TO WHATSAPP", wa_url, use_container_width=True)
                elif not p_detail.whatsapp:
                    st.warning("No WhatsApp number saved for this worker.")

                st.dataframe(history, use_container_width=True, hide_index=True)
                if st.button("❌ Close View"): del st.session_state.view_worker; st.rerun()
                
        if "edit_worker" in st.session_state:
            p_edit = db.query(Person).get(st.session_state.edit_worker)
            if p_edit:
                st.divider()
                st.markdown(f"### ✏️ Editing Worker: {p_edit.name}")
                with st.form("edit_worker_form"):
                    e_name = st.text_input("Name", p_edit.name)
                    e_role = st.text_input("Designation", p_edit.designation)
                    e_phone = st.text_input("Phone", p_edit.phone)
                    e_wa = st.text_input("WhatsApp (Country code first, e.g. 96650...)", p_edit.whatsapp)
                    if st.form_submit_button("Save Changes"):
                        p_edit.name, p_edit.designation = e_name, e_role
                        p_edit.phone, p_edit.whatsapp = e_phone, e_wa
                        db.commit(); del st.session_state.edit_worker; st.rerun()
                if st.button("Cancel Edit"): del st.session_state.edit_worker; st.rerun()

    with tab2:
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown("### ➕ Add New Person")
            with st.form("add_staff"):
                name = st.text_input("Name")
                role = st.text_input("Designation")
                phone = st.text_input("Phone")
                wa = st.text_input("WhatsApp (Include Country Code)")
                pic = st.file_uploader("Photo", type=['jpg','png'])
                if st.form_submit_button("Add Person"):
                    path = save_file(pic)
                    db.add(Person(name=name, designation=role, phone=phone, whatsapp=wa, photo_path=path))
                    db.commit(); st.success("Added!"); st.rerun()
        with c2:
            st.markdown("### 📝 Log & Edit Work")
            p_list = {p.name: p for p in staff}
            target = st.selectbox("Select Person", list(p_list.keys()) if p_list else [])
            if target:
                p = p_list[target]
                t_tab, o_tab, manage_tab = st.tabs(["🚛 ADD TRIPS", "⏱️ ADD OVERTIME", "⚙️ MANAGE HISTORY"])
                with t_tab:
                    with st.form("add_trip"):
                        d_date = st.date_input("Date", key="t_date")
                        d_count = st.number_input("Trips", min_value=1, value=1)
                        if st.form_submit_button("Save Trip"):
                            db.add(Trip(driver_id=p.id, date=d_date, trip_count=d_count)); db.commit(); st.success("Logged!"); st.rerun()
                with o_tab:
                    with st.form("add_ot_d"):
                        o_date = st.date_input("Date", key="o_date_d")
                        o_hrs = st.number_input("Hours", min_value=0.5, step=0.5)
                        if st.form_submit_button("Save OT"):
                            db.add(Overtime(worker_id=p.id, date=o_date, hours=o_hrs, reason="Standard")); db.commit(); st.success("Logged!"); st.rerun()
                with manage_tab:
                    st.write("**Edit or Delete Trips**")
                    person_trips = db.query(Trip).filter(Trip.driver_id == p.id).all()
                    if person_trips:
                        trip_data = [{"ID": t.id, "Date": t.date.date(), "Trips": t.trip_count} for t in person_trips]
                        edited_trips = st.data_editor(trip_data, key=f"edit_trips_{p.id}", use_container_width=True)
                        if st.button("💾 Save Trip Changes", key=f"save_trip_{p.id}"):
                            for row in edited_trips:
                                tr = db.query(Trip).get(row["ID"])
                                if tr: tr.trip_count = row["Trips"]
                            db.commit(); st.success("Trips Updated!"); st.rerun()
                    
                    st.write("**Edit or Delete Overtime**")
                    person_ot = db.query(Overtime).filter(Overtime.worker_id == p.id).all()
                    if person_ot:
                        ot_data = [{"ID": o.id, "Date": o.date.date(), "Hours": o.hours} for o in person_ot]
                        edited_ot = st.data_editor(ot_data, key=f"edit_ot_{p.id}", use_container_width=True)
                        if st.button("💾 Save Overtime Changes", key=f"save_ot_{p.id}"):
                            for row in edited_ot:
                                otr = db.query(Overtime).get(row["ID"])
                                if otr: otr.hours = float(row["Hours"])
                            db.commit(); st.success("Overtime Updated!"); st.rerun()

    with tab3:
        st.markdown("### 🖨️ Ultra HD Print Center")
        perm_url = "https://plant-tracker-vanua8refkhappxfm3rjvwu.streamlit.app/" 
        base_url = st.text_input("App Network URL (Permanent):", value=perm_url)
        
        c1, c2 = st.columns(2)
        with c1:
            if st.button("📄 Generate Joint PDF Sheet"):
                pdf_bytes = create_joint_pdf(staff, base_url)
                st.download_button("📥 Download PDF", pdf_bytes, "Staff_QR_Sheet.pdf", "application/pdf")
        with c2:
            if st.button("📦 Download Individual PNGs (ZIP)"):
                zip_buf = io.BytesIO()
                with zipfile.ZipFile(zip_buf, "w") as zf:
                    for p in staff: zf.writestr(f"{p.name}_QR.png", create_worker_card(p, base_url))
                st.download_button("📥 Save ZIP", zip_buf.getvalue(), "Individual_Cards.zip")
        
        st.divider()
        cols = st.columns(3)
        for i, p in enumerate(staff):
            with cols[i % 3]:
                card = create_worker_card(p, base_url)
                st.image(card, use_container_width=True)

elif menu == "🏗️ CONCRETE DATA":
    st.markdown("<h2>CONCRETE PRODUCTION</h2>", unsafe_allow_html=True)
    with st.expander("➕ ADD RECORD", expanded=False):
        with st.form("conc_form"):
            c1, c2, c3, c4 = st.columns(4)
            d, site = c1.date_input("Date"), c2.text_input("Site Name")
            grade = c3.selectbox("Grade", ["C10", "C20", "C30", "C35", "C40", "C50", "Blinding"])
            qty = c4.number_input("Quantity (m3)")
            if st.form_submit_button("SAVE RECORD"):
                db.add(ConcreteRecord(date=d, site_name=site, grade=grade, quantity=qty)); db.commit(); st.success("Saved!"); st.rerun()
    
    st.markdown("### 📝 Edit Existing Records")
    m = st.selectbox("Month", range(1, 13), index=datetime.now().month-1)
    records = db.query(ConcreteRecord).filter(func.extract('month', ConcreteRecord.date) == m).all()
    
    if records:
        record_data = [{"ID": r.id, "Date": r.date.date(), "Site": r.site_name, "Grade": r.grade, "Quantity": r.quantity} for r in records]
        edited_records = st.data_editor(record_data, use_container_width=True, key="conc_editor")
        if st.button("💾 Save Concrete Changes"):
            for row in edited_records:
                rec = db.query(ConcreteRecord).get(row["ID"])
                if rec:
                    rec.site_name, rec.grade, rec.quantity = row["Site"], row["Grade"], float(row["Quantity"])
            db.commit(); st.success("Updated!"); st.rerun()

elif menu == "📊 EXPORT":
    st.title("Reports Center")
    people = db.query(Person).all()
    target = st.selectbox("Select Person", [p.name for p in people])
    if st.button("Generate Excel"):
        p = db.query(Person).filter_by(name=target).first()
        history = get_detailed_history(p.id)
        fname = generate_excel(history, f"{p.name}_Report", "Records")
        with open(fname, "rb") as f: st.download_button("Download", f, file_name=fname)

elif menu == "⚙️ SETTINGS":
    st.title("Settings")
    key_input = st.text_input("AI API Key", value=settings.ai_api_key or "", type="password")
    if st.button("SAVE KEY"): settings.ai_api_key = key_input; db.commit(); st.success("Saved!")
    with st.form("sets"):
        comp, op = st.text_input("Company", settings.company_name), st.text_input("Operator", settings.operator_name)
        ban, log = st.file_uploader("Banner", type=['jpg','png']), st.file_uploader("Logo", type=['jpg','png'])
        if st.form_submit_button("SAVE VISUALS"):
            settings.company_name, settings.operator_name = comp, op
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
                response = model.generate_content(f"Plant {settings.company_name}, Concrete={conc_sum}. Question: {prompt}")
                bot_reply = response.text
            except: bot_reply = "AI Error."
            st.session_state.chat_history.append(("assistant", bot_reply))
            with st.chat_message("assistant"): st.write(bot_reply)
