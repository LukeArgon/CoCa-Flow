import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
from streamlit_autorefresh import st_autorefresh

# 1. Configurazione Pagina
st.set_page_config(page_title="CoCa_Flow Live", page_icon="🔥", layout="centered")

# 2. Refresh Automatico (Ogni 5 secondi)
# Questo fa sì che l'app si aggiorni da sola per mostrare nuovi dati
st_autorefresh(interval=5000, key="datarefresh")

# 3. Connessione a Firebase
@st.cache_resource
def get_db():
    key_dict = st.secrets["firebase"]
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict['project_id'])

db = get_db()

st.title("🔥 CoCa_Flow Live")

# --- LOGICA DI ACCESSO ---
if 'user_name' not in st.session_state:
    st.info("Benvenuto! Registrati per vedere chi è online.")
    with st.form("login_form"):
        nome = st.text_input("Il tuo Nome")
        ruolo = st.selectbox("Ruolo", ["Partecipante", "Capo Gruppo"])
        submit = st.form_submit_button("Entra nella Sessione")
        
        if submit and nome:
            st.session_state.user_name = nome
            st.session_state.ruolo = ruolo
            # Salviamo su Firebase
            db.collection("partecipanti").document(nome).set({
                "nome": nome, 
                "ruolo": ruolo,
                "ultimo_accesso": firestore.SERVER_TIMESTAMP
            })
            st.rerun()
else:
    # --- INTERFACCIA LIVE ---
    st.sidebar.markdown(f"Utente: **{st.session_state.user_name}**")
    st.sidebar.markdown(f"Ruolo: `{st.session_state.ruolo}`")
    
    if st.sidebar.button("Esci"):
        db.collection("partecipanti").document(st.session_state.user_name).delete()
        del st.session_state.user_name
        st.rerun()

    st.subheader("👥 Partecipanti in tempo reale")
    
    # Leggiamo i partecipanti dal database
    utenti_ref = db.collection("partecipanti").stream()
    
    col1, col2 = st.columns(2)
    with col1:
        st.write("**Capi Gruppo 👑**")
        for u in utenti_ref:
            dati = u.to_dict()
            if dati.get('ruolo') == "Capo Gruppo":
                st.success(f"{dati['nome']}")
    
    # Reset dello stream per la seconda colonna (necessario con firestore stream)
    utenti_ref = db.collection("partecipanti").stream()
    with col2:
        st.write("**Partecipanti 👤**")
        for u in utenti_ref:
            dati = u.to_dict()
            if dati.get('ruolo') == "Partecipante":
                st.info(f"{dati['nome']}")
