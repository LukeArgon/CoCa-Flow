import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import io
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CoCa Flow", layout="wide")

# Refresh automatico ogni 3 secondi per il tempo reale
st_autorefresh(interval=3000, key="datarefresh")

# --- FUNZIONI UTILI ---
@st.cache_resource
def get_db():
    key_dict = st.secrets["firebase"]
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict['project_id'])

db = get_db()

def clean_data_for_excel(data_list):
    """
    Pulisce i dati per Excel: converte le date Firestore (con fuso orario)
    in semplici stringhe di testo per evitare errori.
    """
    cleaned_list = []
    for item in data_list:
        new_item = item.copy()
        # Rimuoviamo chiavi interne di ordinamento se presenti
        if '_dt' in new_item: del new_item['_dt']
        
        # Scorriamo tutte le chiavi e convertiamo le date in stringhe
        for k, v in new_item.items():
            if isinstance(v, datetime):
                # Formato: 2023-10-25 14:30
                new_item[k] = v.strftime('%Y-%m-%d %H:%M:%S')
        cleaned_list.append(new_item)
    return cleaned_list

# --- GESTIONE LOGIN E STATO ---
if 'user' not in st.session_state:
