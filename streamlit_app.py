import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account

# Configurazione Pagina
st.set_page_config(page_title="Co.Ca. Flow", page_icon="🔥")

# Connessione sicura a Firebase
@st.cache_resource # Evita di riconnettersi ogni volta che la pagina si aggiorna
def get_db():
    key_dict = st.secrets["firebase"]
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict['project_id'])

db = get_db()

st.title("Co.Ca. Flow")

# Login Semplice
if 'user_name' not in st.session_state:
    nome = st.text_input("Inserisci il tuo nome per entrare:")
    if st.button("Entra"):
        if nome:
            st.session_state.user_name = nome
            # Salva sul database
            db.collection("partecipanti").document(nome).set({"nome": nome, "stato": "online"})
            st.rerun()
else:
    st.write(f"Ciao **{st.session_state.user_name}**! Sei connesso.")
    
    # Mostra chi altro è online (In tempo reale)
    st.subheader("Persone connesse:")
    utenti = db.collection("partecipanti").stream()
    for u in utenti:
        st.write(f"• {u.id}")

    if st.button("Esci"):
        db.collection("partecipanti").document(st.session_state.user_name).delete()
        del st.session_state.user_name
        st.rerun()
