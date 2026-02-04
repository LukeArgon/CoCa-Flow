import streamlit as st
from google.cloud import firestore
from google.oauth2 import service_account
from streamlit_autorefresh import st_autorefresh
import pandas as pd
import base64
import time
from datetime import datetime

# --- CONFIGURAZIONE PAGINA ---
st.set_page_config(page_title="CoCa_Flow Pro", page_icon="🔥", layout="wide")

# Refresh automatico ogni 3 secondi per il tempo reale
st_autorefresh(interval=3000, key="datarefresh")

# --- FUNZIONI UTILI ---
@st.cache_resource
def get_db():
    key_dict = st.secrets["firebase"]
    creds = service_account.Credentials.from_service_account_info(key_dict)
    return firestore.Client(credentials=creds, project=key_dict['project_id'])

db = get_db()

def img_to_base64(file):
    """Converte l'immagine caricata in una stringa per salvarla nel DB"""
    if file is None: return None
    return base64.b64encode(file.read()).decode('utf-8')

# --- GESTIONE LOGIN E STATO ---
if 'user' not in st.session_state:
    col1, col2 = st.columns([1, 2])
    with col1:
        # Icona generica
        st.write("🔥")
    with col2:
        st.title("Benvenuto in CoCa_Flow")
        st.write("Sistema di gestione riunioni collaborativo.")

    with st.form("login"):
        nome = st.text_input("Il tuo nome")
        ruolo = st.selectbox("Scegli il tuo ruolo", ["Partecipante", "Capo Gruppo"])
        foto = st.file_uploader("Foto Profilo (Opzionale)", type=['png', 'jpg'], help="Max 1MB")
        submit = st.form_submit_button("Entra nella Sessione")

        if submit and nome:
            foto_str = img_to_base64(foto)
            user_data = {
                "nome": nome,
                "ruolo": ruolo,
                "foto": foto_str,
                "online": True,
                "ultimo_accesso": firestore.SERVER_TIMESTAMP
            }
            # Salva/Aggiorna utente su Firebase
            db.collection("partecipanti").document(nome).set(user_data)
            st.session_state.user = user_data
            st.rerun()

else:
    # --- UTENTE LOGGATO: INTERFACCIA PRINCIPALE ---
    me = st.session_state.user
    is_admin = me['ruolo'] == "Capo Gruppo"

    # Sidebar: Info Sessione e Utente
    with st.sidebar:
        if me.get('foto'):
            st.markdown(f'<img src="data:image/png;base64,{me["foto"]}" style="border-radius:50%; width:100px;">', unsafe_allow_html=True)
        st.title(f"Ciao, {me['nome']}")
        st.caption(f"Ruolo: {me['ruolo']}")
        
        # Gestione Titolo Sessione (Solo Admin)
        session_ref = db.collection("config").document("sessione")
        session_doc = session_ref.get()
        if session_doc.exists:
            session_data = session_doc.to_dict()
            current_title = session_data.get('titolo', "Nuova Riunione")
        else:
            current_title = "Nuova Riunione"
            session_ref.set({"titolo": "Nuova Riunione"})
        
        if is_admin:
            new_title = st.text_input("Titolo Sessione", value=current_title)
            if new_title != current_title:
                session_ref.set({"titolo": new_title}, merge=True)
        else:
            st.subheader(current_title)

        st.divider()
        if st.button("Esci dalla sessione", type="primary"):
            db.collection("partecipanti").document(me['nome']).delete()
            del st.session_state.user
            st.rerun()

    # --- CORPO PRINCIPALE ---
    st.title(f"🔥 {current_title}")
    
    tab1, tab2, tab3, tab4 = st.tabs(["📢 Discussione Live", "📝 Gestione Argomenti", "👥 Partecipanti", "🗄️ Archivio"])

    # ---------------------------------------------------------
    # TAB 1: DISCUSSIONE LIVE (Argomento Attivo e Coda)
    # ---------------------------------------------------------
    with tab1:
        # Recupera Argomento Attivo
        topics_ref = db.collection("topics").where("stato", "==", "attivo").stream()
        active_topic = None
        active_topic_id = None
        for t in topics_ref:
            active_topic = t.to_dict()
            active_topic_id = t.id
        
        if active_topic:
            # Controllo Privacy
            if active_topic.get('privato') and not is_admin:
                st.warning("🔒 Discussione privata in corso tra i Capi Gruppo.")
            else:
                st.info(f"Argomento in corso: **{active_topic['titolo']}**")
                st.markdown(f"_{active_topic['descrizione']}_")
                
                # Visualizzazione Tag
                tags = []
                if active_topic.get('urgente'): tags.append("🔴 URGENTE")
                if active_topic.get('delicato'): tags.append("⚠️ DELICATO")
                if tags: st.write(" ".join(tags))

                # --- GESTIONE CODA ---
                st.write("---")
                col_coda_btn, col_coda_list = st.columns([1, 2])
                
                with col_coda_btn:
                    st.write("### Vuoi parlare?")
                    if st.button("✋ Mettimi in coda"):
                        queue_data = {
                            "nome": me['nome'],
                            "topic_id": active_topic_id,
                            "timestamp": time.time()
                        }
                        db.collection("coda").document(me['nome']).set(queue_data)
                        st.toast("Sei in coda!")
                    
                    if st.button("❌ Togli dalla coda"):
                        db.collection("coda").document(me['nome']).delete()

                with col_coda_list:
                    st.write("### 🗣️ Coda Interventi")
                    # FIX: Recuperiamo tutto e ordiniamo in Python per evitare errori di indice
                    queue_ref = db.collection("coda").where("topic_id", "==", active_topic_id).stream()
                    
                    queue_list = []
                    for q in queue_ref:
                        q_data = q.to_dict()
                        q_data['id'] = q.id
                        queue_list.append(q_data)
                    
                    # Ordiniamo la lista in Python per timestamp
                    queue_list.sort(key=lambda x: x['timestamp'])

                    if not queue_list:
                        st.write("Nessuno in coda.")
                    
                    for idx, q_data in enumerate(queue_list):
                        col_q1, col_q2 = st.columns([4, 1])
                        with col_q1:
                            st.write(f"**{idx + 1}. {q_data['nome']}**")
                        
                        # Gestione Admin della Coda
                        if is_admin:
                            with col_q2:
                                if st.button("🗑️", key=f"del_{q_data['id']}"):
                                    db.collection("coda").document(q_data['id']).delete()
                                    st.rerun()

                # Tasto per chiudere l'argomento (Admin)
                if is_admin:
                    st.write("---")
                    if st.button("✅ Concludi Argomento"):
                        db.collection("topics").document(active_topic_id).update({"stato": "concluso", "fine": firestore.SERVER_TIMESTAMP})
                        # Pulisce la coda
                        batch = db.batch()
                        # Nota: dobbiamo rileggere i riferimenti per cancellarli
                        q_to_delete = db.collection("coda").where("topic_id", "==", active_topic_id).stream()
                        for q in q_to_delete:
                            batch.delete(q.reference)
                        batch.commit()
                        st.rerun()

        else:
            st.info("Nessun argomento attivo al momento. Proponine uno nella scheda 'Gestione Argomenti'!")

    # ---------------------------------------------------------
    # TAB 2: GESTIONE ARGOMENTI (Proposte e Cronologia)
    # ---------------------------------------------------------
    with tab2:
        col_prop, col_hist = st.columns(2)
        
        with col_prop:
            st.subheader("💡 Proponi Nuovo Argomento")
            with st.form("new_topic"):
                t_titolo = st.text_input("Titolo")
                t_desc = st.text_area("Descrizione")
                c1, c2, c3 = st.columns(3)
                t_urgente = c1.checkbox("Urgente")
                t_privato = c2.checkbox("Privato (Solo Admin)")
                t_delicato = c3.checkbox("Delicato")
                
                if st.form_submit_button("Invia Proposta"):
                    db.collection("topics").add({
                        "titolo": t_titolo,
                        "descrizione": t_desc,
                        "urgente": t_urgente,
                        "privato": t_privato,
                        "delicato": t_delicato,
                        "proponente": me['nome'],
                        "stato": "proposto", # proposto, attivo, concluso
                        "data": firestore.SERVER_TIMESTAMP
                    })
                    st.success("Argomento proposto!")

            st.subheader("📌 Argomenti Proposti")
            proposti = db.collection("topics").where("stato", "==", "proposto").stream()
            for p in proposti:
                p_data = p.to_dict()
                # Filtro privacy
                if p_data.get('privato') and not is_admin:
                    continue
                    
                with st.expander(f"{p_data['titolo']} ({p_data['proponente']})"):
                    st.write(p_data['descrizione'])
                    tags = []
                    if p_data.get('urgente'): tags.append("🔴 URGENTE")
                    if p_data.get('privato'): tags.append("🔒 PRIVATO")
                    st.write(" ".join(tags))
                    
                    if is_admin:
                        if st.button("🚀 Avvia Discussione", key=f"start_{p.id}"):
                            # Disattiva eventuali altri topic attivi
                            old_active = db.collection("topics").where("stato", "==", "attivo").stream()
                            for old in old_active:
                                old.reference.update({"stato": "concluso"})
                            
                            # Attiva questo
                            db.collection("topics").document(p.id).update({"stato": "attivo"})
                            st.rerun()

        with col_hist:
            st.subheader("📜 Cronologia (Topic History)")
            # FIX: Rimosso l'order_by nella query per evitare errore Missing Index
            history_stream = db.collection("topics").where("stato", "==", "concluso").stream()
            
            # Convertiamo in lista per ordinare in Python
            history_list = []
            for h in history_stream:
                h_data = h.to_dict()
                if h_data.get('privato') and not is_admin: continue
                # Gestione sicura della data (alcune date potrebbero essere None se appena create)
                if 'data' not in h_data or h_data['data'] is None:
                    # Usiamo una data fittizia vecchia se manca
                    h_data['_sort_date'] = datetime.min
                else:
                    h_data['_sort_date'] = h_data['data']
                
                history_list.append(h_data)
            
            # Ordiniamo Python-side (più recente in alto)
            history_list.sort(key=lambda x: x['_sort_date'], reverse=True)
            
            for h_data in history_list:
                st.text(f"✅ {h_data['titolo']}")
                st.caption(h_data.get('descrizione', ''))
                st.divider()

    # ---------------------------------------------------------
    # TAB 3: PARTECIPANTI
    # ---------------------------------------------------------
    with tab3:
        st.subheader("Utenti Online")
        users = db.collection("partecipanti").stream()
        
        for u in users:
            u_data = u.to_dict()
            col_u1, col_u2, col_u3 = st.columns([1, 3, 1])
            
            with col_u1:
                if u_data.get('foto'):
                     st.markdown(f'<img src="data:image/png;base64,{u_data["foto"]}" style="border-radius:50%; width:50px;">', unsafe_allow_html=True)
                else:
                    st.write("👤")
            
            with col_u2:
                role_icon = "👑" if u_data['ruolo'] == "Capo Gruppo" else ""
                st.write(f"**{u_data['nome']}** {role_icon}")
                st.caption(u_data['ruolo'])
            
            with col_u3:
                # Rimozione Partecipante (Solo Admin e non se stesso)
                if is_admin and u_data['nome'] != me['nome']:
                    if st.button("KICK", key=f"kick_{u.id}"):
                        db.collection("partecipanti").document(u.id).delete()
                        st.warning(f"{u_data['nome']} rimosso.")
                        st.rerun()

    # ---------------------------------------------------------
    # TAB 4: ARCHIVIO E EXPORT
    # ---------------------------------------------------------
    with tab4:
        st.header("🗄️ Archiviazione Sessione")
        
        # Sezione Export CSV/TXT
        st.subheader("Esporta Dati Cronologia")
        # Usiamo la lista history_list già calcolata nel Tab 2 se esiste, altrimenti ricalcoliamo
        if 'history_list' in locals() and history_list:
            # Pulizia dati per CSV (rimuoviamo colonne tecniche)
            clean_history = []
            for item in history_list:
                clean_item = {k: v for k, v in item.items() if k != '_sort_date'}
                clean_history.append(clean_item)

            df = pd.DataFrame(clean_history)
            csv = df.to_csv(index=False).encode('utf-8')
            
            st.download_button(
                label="Scarica Report CSV",
                data=csv,
                file_name=f'report_sessione.csv',
                mime='text/csv',
            )
        else:
            st.write("Nessun dato concluso da esportare.")

        st.divider()
        
        # Sezione Archiviazione (Snapshot)
        st.subheader("Salva Sessione Corrente")
        archive_name = st.text_input("Nome Archivio", value=f"Backup {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        
        if st.button("Archivia Tutto Ora"):
            # Creiamo un documento snapshot
            # Raccogliamo i dati puliti
            all_users = [u.to_dict() for u in db.collection("partecipanti").stream()]
            # Raccogliamo topic history (ricalcoliamo per sicurezza)
            hist_ref = db.collection("topics").where("stato", "==", "concluso").stream()
            hist_data_save = [h.to_dict() for h in hist_ref]

            snapshot = {
                "titolo_sessione": current_title,
                "data_archiviazione": firestore.SERVER_TIMESTAMP,
                "topics_history": hist_data_save,
                "partecipanti_al_momento": all_users
            }
            db.collection("archivi").document(archive_name).set(snapshot)
            st.success(f"Sessione '{archive_name}' archiviata con successo!")
        
        # Lista Archivi
        st.subheader("Archivi Passati")
        archives = db.collection("archivi").stream()
        for arch in archives:
            a_data = arch.to_dict()
            with st.expander(f"📁 {arch.id}"):
                st.write(f"**Titolo Originale:** {a_data.get('titolo_sessione')}")
                st.write(f"**Topics discussi:** {len(a_data.get('topics_history', []))}")
                if st.button("Elimina Archivio", key=f"del_arch_{arch.id}"):
                    db.collection("archivi").document(arch.id).delete()
                    st.rerun()
