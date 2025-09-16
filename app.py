import streamlit as st
from supabase import create_client
import pandas as pd

st.set_page_config(page_title="SKU Sinonime — ServicePack", page_icon="🔎", layout="centered")

# --- Supabase client ---
@st.cache_resource
def get_client():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["anon_key"]
    return create_client(url, key)

sb = get_client()

TABLE = "sku_sinonime"
COL_ALT = '"COD ALTERNATIV"'
COL_MAIN = '"COD PRINCIPAL"'
COL_NAME = '"NUME"'

st.title("🔎 Gestionare sinonime SKU")
st.caption("Caută după **COD PRINCIPAL**, vezi aliasuri și adaugă rapid coduri alternative. Numele se completează automat.")

# --- Helpers ---
def norm(s: str) -> str:
    if s is None:
        return ""
    return (
        s.replace("\u00A0", " ")   # NBSP -> spatiu normal
         .replace("\u200B", "")   # zero-width space
         .strip()
         .upper()
    )

def get_nume_for_principal(cod_principal: str):
    res = (
        sb.table(TABLE)
        .select(COL_NAME)
        .filter(COL_MAIN, "eq", cod_principal)
        .limit(1)
        .execute()
    )
    if res.data:
        return res.data[0]["NUME"]
    return None

def get_aliases(cod_principal: str):
    res = (
        sb.table(TABLE)
        .select(f"{COL_ALT},{COL_MAIN},{COL_NAME}")
        .filter(COL_MAIN, "eq", cod_principal)
        .order(COL_ALT)
        .execute()
    )
    return res.data or []

def alt_exists(alt_code: str) -> bool:
    res = (
        sb.table(TABLE)
        .select(COL_ALT)
        .filter(COL_ALT, "eq", alt_code)
        .limit(1)
        .execute()
    )
    return bool(res.data)

# --- UI ---
with st.form("search_form", clear_on_submit=False):
    cod_principal_input = st.text_input("COD PRINCIPAL", placeholder="ex: 02351QCY").strip()
    submitted = st.form_submit_button("Caută")
    if submitted and not cod_principal_input:
        st.warning("Completează COD PRINCIPAL.")
        st.stop()

if cod_principal_input:
    cod_principal = norm(cod_principal_input)
    st.subheader(f"Rezultate pentru: `{cod_principal}`")

    # Afișează sinonimele existente
    rows = get_aliases(cod_principal)
    if rows:
        df = pd.DataFrame(rows)
        st.dataframe(df, use_container_width=True, hide_index=True)
        nume_ref = rows[0]["NUME"]
    else:
        nume_ref = get_nume_for_principal(cod_principal)
        st.info("Nu există încă rânduri pentru acest COD PRINCIPAL. Poți adăuga unul nou mai jos.")

    # Adăugare coduri alternative
    st.markdown("### ➕ Adaugă coduri alternative")
    new_codes_raw = st.text_area(
        "Coduri alternative (separate prin virgulă sau pe linii noi)",
        placeholder="ALT001, ALT002\nALT003"
    )

    if st.button("Adaugă acum"):
        if not new_codes_raw.strip():
            st.warning("Introdu cel puțin un cod alternativ.")
        else:
            # Normalizează lista
            parts = [norm(x) for x in new_codes_raw.replace(",", "\n").split("\n")]
            new_codes = [x for x in parts if x]

            # Asigură NUME (dintr-un rând existent)
            nume = nume_ref or get_nume_for_principal(cod_principal)
            if not nume:
                # Dacă nu există încă nume pentru principal, cere-l de la utilizator și creează rândul de referință
                st.warning("Nu am găsit denumirea produsului pentru acest COD PRINCIPAL.")
                nume = st.text_input("Introdu denumirea produsului (NUME) pentru a crea rândul de referință").strip()
                if not nume:
                    st.stop()

            inserted, skipped = [], []

            # Seed rând de referință dacă lipsesc rânduri pentru principal (ALT=PRINCIPAL)
            if not rows:
                try:
                    sb.table(TABLE).insert({
                        "COD ALTERNATIV": cod_principal,
                        "COD PRINCIPAL": cod_principal,
                        "NUME": nume
                    }).execute()
                except Exception:
                    # e posibil să existe deja
                    pass

            # Inserare coduri alternative
            for alt in new_codes:
                if alt == cod_principal or alt_exists(alt):
                    skipped.append(alt)
                    continue
                payload = {
                    "COD ALTERNATIV": alt,
                    "COD PRINCIPAL": cod_principal,
                    "NUME": nume
                }
                try:
                    sb.table(TABLE).insert(payload).execute()
                    inserted.append(alt)
                except Exception as e:
                    st.error(f"Eroare la inserarea {alt}: {e}")

            if inserted:
                st.success(f"Adăugate: {', '.join(inserted)}")
            if skipped:
                st.info(f"Sărite (existente/identice cu principal): {', '.join(skipped)}")

            # Refresh tabel
            rows = get_aliases(cod_principal)
            if rows:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Ștergere simplă
    st.divider()
    st.markdown("### 🗑️ Șterge un cod alternativ")
    del_alt = st.text_input("Cod alternativ de șters", placeholder="ALT001").strip()
    if st.button("Șterge"):
        del_alt_n = norm(del_alt)
        if not del_alt_n:
            st.warning("Completează codul alternativ.")
        elif del_alt_n == cod_principal:
            st.warning("Nu poți șterge rândul de referință (ALT=PRINCIPAL).")
        else:
            sb.table(TABLE).delete().filter(COL_ALT, "eq", del_alt_n).execute()
            st.success(f"Șters: {del_alt_n}")
