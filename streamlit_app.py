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
    Pulisce i dati per Excel: converte date in stringhe e formatta gli appunti raccolti.
    """
    cleaned_list = []
    for item in data_list:
        new_item = item.copy()
        if '_dt' in new_item: del new_item['_dt']
        
        # Formattazione speciale per la lista degli appunti salvati
        if 'note_raccolte' in new_item and isinstance(new_item['note_raccolte'], list):
            # Converte la lista di oggetti in una stringa leggibile (Es: "Mario: nota...\nLuigi: nota...")
            text_notes = ""
            for note in new_item['note_raccolte']:
                text_notes += f"[{note['autore']}]: {note['testo']}\n"
            new_item['note_raccolte'] = text_notes

        # Scorriamo tutte le chiavi e convertiamo le date in stringhe
        for k, v in new_item.items():
            if isinstance(v, datetime):
                new_item[k] = v.strftime('%Y-%m-%d %H:%M:%S')
                
        cleaned_list.append(new_item)
    return cleaned_list

# --- GESTIONE LOGIN E STATO ---
if 'user' not in st.session_state:
    st.title("CoCa Flow - Accesso")
    st.write("Sistema di gestione riunioni.")

    with st.form("login"):
        nome = st.text_input("Nome Cognome")
        ruolo = st.selectbox("Ruolo", ["Partecipante", "Capo Gruppo"])
        submit = st.form_submit_button("Accedi")

        if submit and nome:
            user_data = {
                "nome": nome,
                "ruolo": ruolo,
                "online": True,
                "ultimo_accesso": firestore.SERVER_TIMESTAMP,
                # Campo temporaneo per gli appunti del topic CORRENTE
                "appunti_topic_corrente": "" 
            }
            # Salvataggio con merge per non perdere dati
            db.collection("partecipanti").document(nome).set(user_data, merge=True)
            
            # Recuperiamo il valore attuale dal DB (utile se rientra dopo crash)
            doc = db.collection("partecipanti").document(nome).get()
            if doc.exists:
                user_data['appunti_topic_corrente'] = doc.to_dict().get('appunti_topic_corrente', "")

            st.session_state.user = user_data
            st.rerun()

else:
    # --- UTENTE LOGGATO ---
    me = st.session_state.user
    is_admin = me['ruolo'] == "Capo Gruppo"
    current_user_ref = db.collection("partecipanti").document(me['nome'])

    # Sync Appunti dal DB alla Sessione (per assicurarsi che siano puliti quando l'admin chiude il topic)
    # Leggiamo lo stato aggiornato dal DB
    remote_user_data = current_user_ref.get().to_dict()
    if remote_user_data:
        # Se nel DB è vuoto ma in locale ho testo, significa che è stato resettato dall'admin?
        # No, fidiamoci del DB. Se l'admin ha pulito, nel DB è vuoto.
        st.session_state.user['appunti_topic_corrente'] = remote_user_data.get('appunti_topic_corrente', "")

    with st.sidebar:
        st.header(me['nome'])
        st.caption(f"Ruolo: {me['ruolo']}")
        
        session_ref = db.collection("config").document("sessione")
        session_doc = session_ref.get()
        if session_doc.exists:
            session_data = session_doc.to_dict()
            current_title = session_data.get('titolo', "Nuova Riunione")
        else:
            current_title = "Nuova Riunione"
            session_ref.set({"titolo": "Nuova Riunione"})
        
        if is_admin:
            st.write("---")
            new_title = st.text_input("Titolo Riunione", value=current_title)
            if new_title != current_title:
                session_ref.set({"titolo": new_title}, merge=True)
        else:
            st.write("---")
            st.subheader(current_title)

        st.write("---")
        if st.button("Disconnetti", type="primary"):
            db.collection("partecipanti").document(me['nome']).delete()
            del st.session_state.user
            st.rerun()

    # --- CORPO PRINCIPALE ---
    st.title(f"{current_title}")
    
    tab1, tab2, tab3, tab4 = st.tabs(["Discussione Live", "Gestione Argomenti", "Partecipanti", "Archivio"])

    # ---------------------------------------------------------
    # TAB 1: DISCUSSIONE LIVE + APPUNTI TOPIC
    # ---------------------------------------------------------
    with tab1:
        # Recupera Argomento Attivo
        topics_ref = db.collection("topics").where("stato", "==", "attivo").stream()
        active_topic = None
        active_topic_id = None
        for t in topics_ref:
            active_topic = t.to_dict()
            active_topic_id = t.id
        
        col_live, col_notes = st.columns([2, 1])

        if active_topic:
            with col_live:
                if active_topic.get('privato') and not is_admin:
                    st.warning("Discussione privata in corso (Riservata ai Capi Gruppo).")
                else:
                    st.info(f"ARGOMENTO: {active_topic['titolo']}")
                    st.write(f"{active_topic['descrizione']}")
                    
                    tags = []
                    if active_topic.get('urgente'): tags.append("[URGENTE]")
                    if active_topic.get('delicato'): tags.append("[DELICATO]")
                    if tags: st.markdown(f"**Etichette:** {' '.join(tags)}")

                    st.write("---")
                    
                    c_btn, c_list = st.columns([1, 2])
                    with c_btn:
                        st.write("**Azioni:**")
                        if st.button("Prenotati per parlare"):
                            queue_data = {"nome": me['nome'], "topic_id": active_topic_id, "timestamp": time.time()}
                            db.collection("coda").document(me['nome']).set(queue_data)
                            st.success("Sei in coda.")
                        
                        if st.button("Annulla prenotazione"):
                            db.collection("coda").document(me['nome']).delete()

                    with c_list:
                        st.write("**Coda Interventi:**")
                        queue_ref = db.collection("coda").where("topic_id", "==", active_topic_id).stream()
                        queue_list = []
                        for q in queue_ref:
                            q_d = q.to_dict()
                            q_d['id'] = q.id
                            queue_list.append(q_d)
                        queue_list.sort(key=lambda x: x['timestamp'])

                        if not queue_list: st.write("Nessuna prenotazione.")
                        for idx, q_data in enumerate(queue_list):
                            col_q1, col_q2 = st.columns([4, 1])
                            with col_q1: st.write(f"{idx + 1}. {q_data['nome']}")
                            if is_admin:
                                with col_q2:
                                    if st.button("X", key=f"del_{q_data['id']}"):
                                        db.collection("coda").document(q_data['id']).delete()
                                        st.rerun()

                    if is_admin:
                        st.write("---")
                        # LOGICA DI CHIUSURA ARGOMENTO E RACCOLTA APPUNTI
                        if st.button("✅ Concludi Argomento e Salva Note"):
                            batch = db.batch()
                            
                            # 1. Recupera gli appunti da TUTTI i partecipanti
                            all_users = db.collection("partecipanti").stream()
                            collected_notes = []
                            
                            for user_doc in all_users:
                                u_data = user_doc.to_dict()
                                notes = u_data.get('appunti_topic_corrente', '').strip()
                                if notes:
                                    collected_notes.append({
                                        "autore": u_data['nome'],
                                        "testo": notes
                                    })
                                    # Resetta il campo appunti dell'utente nel batch
                                    batch.update(user_doc.reference, {"appunti_topic_corrente": ""})
                            
                            # 2. Aggiorna il Topic con stato concluso e le note raccolte
                            topic_ref = db.collection("topics").document(active_topic_id)
                            batch.update(topic_ref, {
                                "stato": "concluso", 
                                "fine": firestore.SERVER_TIMESTAMP,
                                "note_raccolte": collected_notes
                            })

                            # 3. Pulisci coda
                            q_del = db.collection("coda").where("topic_id", "==", active_topic_id).stream()
                            for q in q_del: 
                                batch.delete(q.reference)
                            
                            batch.commit()
                            
                            # Resetta anche session state locale
                            st.session_state.user['appunti_topic_corrente'] = ""
                            st.success("Argomento concluso e appunti salvati!")
                            time.sleep(1) # Un piccolo delay per far leggere
                            st.rerun()

            # COLONNA APPUNTI (Visibile se c'è un topic attivo)
            if not (active_topic.get('privato') and not is_admin):
                with col_notes:
                    st.subheader("I tuoi Appunti")
                    st.caption(f"Note per: **{active_topic['titolo']}**")
                    st.caption("Al termine dell'argomento verranno salvate e il foglio pulito.")
                    
                    initial_notes = st.session_state.user.get('appunti_topic_corrente', "")
                    # Usiamo key dinamica basata sul topic ID per forzare reset visivo se cambia topic
                    notes_input = st.text_area("Scrivi qui...", value=initial_notes, height=400, key=f"notes_{active_topic_id}")
                    
                    if notes_input != initial_notes:
                        st.session_state.user['appunti_topic_corrente'] = notes_input
                        current_user_ref.update({"appunti_topic_corrente": notes_input})
        else:
            with col_live:
                st.info("Nessun argomento attivo. Selezionane uno dalla scheda 'Gestione Argomenti'.")
            with col_notes:
                st.write("Attendi l'avvio di un argomento per prendere appunti.")

    # ---------------------------------------------------------
    # TAB 2: GESTIONE ARGOMENTI
    # ---------------------------------------------------------
    with tab2:
        col_prop, col_hist = st.columns(2)
        
        with col_prop:
            st.subheader("Nuova Proposta")
            with st.form("new_topic"):
                t_titolo = st.text_input("Titolo")
                t_desc = st.text_area("Descrizione")
                c1, c2, c3 = st.columns(3)
                t_urgente = c1.checkbox("Urgente")
                t_privato = c2.checkbox("Privato (Solo Capi)")
                t_delicato = c3.checkbox("Delicato")
                
                if st.form_submit_button("Invia"):
                    db.collection("topics").add({
                        "titolo": t_titolo,
                        "descrizione": t_desc,
                        "urgente": t_urgente,
                        "privato": t_privato,
                        "delicato": t_delicato,
                        "proponente": me['nome'],
                        "stato": "proposto",
                        "data": firestore.SERVER_TIMESTAMP,
                        "note_raccolte": []
                    })
                    st.success("Inserito.")

            st.subheader("In attesa")
            proposti = db.collection("topics").where("stato", "==", "proposto").stream()
            for p in proposti:
                p_data = p.to_dict()
                if p_data.get('privato') and not is_admin: continue
                
                with st.expander(f"{p_data['titolo']} ({p_data['proponente']})"):
                    st.write(p_data['descrizione'])
                    lbls = []
                    if p_data.get('urgente'): lbls.append("**[URGENTE]**")
                    if p_data.get('privato'): lbls.append("**[PRIVATO]**")
                    if p_data.get('delicato'): lbls.append("**[DELICATO]**")
                    if lbls: st.markdown(" ".join(lbls))
                    
                    if is_admin:
                        if st.button("Avvia Discussione", key=f"start_{p.id}"):
                            # Chiusura forzata vecchi
                            old_active = db.collection("topics").where("stato", "==", "attivo").stream()
                            batch_start = db.batch()
                            for old in old_active: 
                                batch_start.update(old.reference, {"stato": "concluso"})
                            
                            batch_start.update(db.collection("topics").document(p.id), {"stato": "attivo"})
                            batch_start.commit()
                            st.rerun()

        with col_hist:
            st.subheader("Cronologia & Verbali")
            h_stream = db.collection("topics").where("stato", "==", "concluso").stream()
            h_list = []
            for h in h_stream:
                d = h.to_dict()
                if d.get('privato') and not is_admin: continue
                if 'data' not in d or d['data'] is None: d['_dt'] = datetime.min
                else: d['_dt'] = d['data']
                h_list.append(d)
            
            h_list.sort(key=lambda x: x['_dt'], reverse=True)
            
            for item in h_list:
                with st.expander(f"✅ {item['titolo']}"):
                    st.caption(item.get('descrizione', ''))
                    
                    # Mostra note raccolte
                    notes = item.get('note_raccolte', [])
                    if notes:
                        st.markdown("**Appunti salvati:**")
                        for n in notes:
                            st.markdown(f"- **{n['autore']}**: {n['testo']}")
                    else:
                        st.write("_Nessun appunto salvato._")

    # ---------------------------------------------------------
    # TAB 3: PARTECIPANTI
    # ---------------------------------------------------------
    with tab3:
        st.subheader("Elenco Presenti")
        users = db.collection("partecipanti").stream()
        for u in users:
            u_data = u.to_dict()
            col_a, col_b, col_c = st.columns([3, 2, 1])
            with col_a: st.write(f"**{u_data['nome']}**")
            with col_b: st.write(f"{u_data['ruolo']}")
            with col_c:
                if is_admin and u_data['nome'] != me['nome']:
                    if st.button("Rimuovi", key=f"kick_{u.id}"):
                        db.collection("partecipanti").document(u.id).delete()
                        st.rerun()

    # ---------------------------------------------------------
    # TAB 4: ARCHIVIO
    # ---------------------------------------------------------
    with tab4:
        st.subheader("Operazioni di Archiviazione")
        
        # 1. EXPORT EXCEL
        if 'h_list' in locals() and h_list:
            data_topics = clean_data_for_excel(h_list)
            df_topics = pd.DataFrame(data_topics)
            
            # Ordine colonne preferito
            cols = ['titolo', 'descrizione', 'note_raccolte', 'proponente', 'urgente', 'delicato']
            # Filtra solo colonne esistenti
            cols = [c for c in cols if c in df_topics.columns]
            df_topics = df_topics[cols]

            pres_now = [u.to_dict() for u in db.collection("partecipanti").stream()]
            data_users = clean_data_for_excel(pres_now)
            df_users = pd.DataFrame(data_users)
            # Rimuovi campo appunti tecnici dai presenti
            if 'appunti_topic_corrente' in df_users.columns:
                df_users = df_users.drop(columns=['appunti_topic_corrente'])

            buffer = io.BytesIO()
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                df_topics.to_excel(writer, sheet_name='Cronologia Argomenti', index=False)
                if not df_users.empty:
                    df_users.to_excel(writer, sheet_name='Presenti', index=False)
                else:
                    pd.DataFrame(["Nessuno"]).to_excel(writer, sheet_name='Presenti')
            
            st.download_button(
                label="Scarica Report Excel (.xlsx)",
                data=buffer.getvalue(),
                file_name=f"Report_{current_title}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.write("Nessun dato storico disponibile per l'export.")

        st.divider()

        # 2. SALVATAGGIO SNAPSHOT
        archive_name = st.text_input("Nome Archivio", value=f"Sessione {datetime.now().strftime('%Y-%m-%d')}")
        if st.button("Salva Archivio nel Cloud"):
            pres_now = [u.to_dict() for u in db.collection("partecipanti").stream()]
            hist_ref_save = db.collection("topics").where("stato", "==", "concluso").stream()
            hist_save = [h.to_dict() for h in hist_ref_save]

            snapshot = {
                "titolo_sessione": current_title,
                "data": firestore.SERVER_TIMESTAMP,
                "topics": hist_save,
                "presenti": pres_now
            }
            db.collection("archivi").document(archive_name).set(snapshot)
            st.success("Archiviato.")

        st.write("---")
        st.subheader("Archivi Passati")
        
        archives = db.collection("archivi").stream()
        for arch in archives:
            a_data = arch.to_dict()
            with st.expander(f"📁 {arch.id} - {a_data.get('titolo_sessione', 'Senza Titolo')}"):
                topic_list = a_data.get('topics', [])
                st.write(f"**Topics ({len(topic_list)}):**")
                for t in topic_list:
                    st.write(f"- {t.get('titolo', '???')}")
                    # Mostra un'anteprima delle note anche qui
                    if t.get('note_raccolte'):
                        st.caption(f"  *({len(t['note_raccolte'])} note salvate)*")

                st.write("---")
                user_list = a_data.get('presenti', [])
                st.write(f"**Presenti ({len(user_list)}):**")
                names = [u.get('nome', '?') for u in user_list]
                st.caption(", ".join(names))

                if st.button("Elimina Archivio", key=f"del_arch_{arch.id}"):
                    db.collection("archivi").document(arch.id).delete()
                    st.rerun()
