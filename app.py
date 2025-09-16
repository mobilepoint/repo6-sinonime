# app.py — Admin aliasuri SKU (căutare după nume, adăugare și ștergere)
import re
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
from supabase import create_client

# =========================
#   CONFIG
# =========================
st.set_page_config(page_title="Admin aliasuri SKU", layout="wide")
st.title("Admin aliasuri SKU")

# =========================
#   SECRETS (Supabase)
# =========================
sb = st.secrets.get("supabase", {})
SUPABASE_URL = sb.get("url", "")
SUPABASE_ANON = sb.get("anon_key", "")
if not SUPABASE_URL or not SUPABASE_ANON:
    st.error("Lipsește [supabase] în Secrets. Exemplu:\n\n[supabase]\nurl = \"https://<proj>.supabase.co\"\nanon_key = \"<ANON>\"")
    st.stop()

client = create_client(SUPABASE_URL, SUPABASE_ANON)

# =========================
#   HELPERS
# =========================
def canon_sku(x: str) -> str:
    """Curăță spații, convertește 5.6061E+11 -> 560610000000."""
    if x is None:
        return ""
    s = str(x).strip().replace(" ", "")
    if s == "":
        return ""
    if re.match(r"^[0-9]+(\.[0-9]+)?[eE]\+[0-9]+$", s):
        try:
            d = Decimal(s)
            s = format(d, 'f').replace(".", "")
        except InvalidOperation:
            pass
    return s

@st.cache_data(ttl=300, show_spinner=False)
def fetch_products(q: str | None):
    """Citește din view-ul public.v_aliases_by_product; filtrează după nume dacă e cazul."""
    rng = 1000
    start = 0
    rows = []
    while True:
        sel = client.table("v_aliases_by_product").select("*")
        if q:
            sel = sel.ilike("name", f"%{q}%")
        resp = sel.order("name").range(start, start + rng - 1).execute()
        data = resp.data or []
        rows.extend(data)
        if len(data) < rng:
            break
        start += rng
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=["product_id", "name", "primary_sku", "all_skus"])
    if "all_skus" in df.columns:
        df["all_skus"] = df["all_skus"].apply(lambda v: v if isinstance(v, list) else [])
    return df

def rpc_add_alias(product_id: str, new_sku: str):
    return client.rpc("add_alias_sku", {"p_product_id": product_id, "p_sku": new_sku}).execute()

def rpc_remove_alias(product_id: str, sku: str):
    return client.rpc("remove_alias_sku", {"p_product_id": product_id, "p_sku": sku}).execute()

# =========================
#   UI
# =========================
search = st.text_input("Caută produs după nume", placeholder="ex: iPhone 11, G935 GOLD, etc.").strip()
df = fetch_products(search or None)

if df.empty:
    st.info("N-am găsit produse pentru criteriul de căutare.")
    st.stop()

left, right = st.columns([2, 3], gap="large")

with left:
    st.subheader("Rezultate")
    st.dataframe(df[["name", "primary_sku"]], use_container_width=True, hide_index=True, height=320)

    options = {f"{row['name']}  —  {row['primary_sku']}": idx for idx, row in df.reset_index().iterrows()}
    choice = st.selectbox("Selectează produsul", list(options.keys()))
    row = df.iloc[options[choice]]
    product_id = row["product_id"]
    name = row["name"]
    primary = row["primary_sku"]
    aliases = sorted([s for s in row["all_skus"] if s != primary])

with right:
    st.subheader("Detalii produs")
    st.markdown(f"**Nume:** {name}")
    st.markdown(f"**SKU principal:** `{primary}`")

    # ===== LISTĂ ALIASURI =====
    st.markdown("**Aliasuri existente:**")
    if aliases:
        st.code(", ".join(aliases), language="text")
    else:
        st.info("Nu există aliasuri pentru acest produs.")

    st.markdown("---")

    # ===== ADĂUGARE ALIASURI =====
    st.markdown("### ➕ Adaugă aliasuri noi")
    raw = st.text_area("SKU-uri de adăugat (separate prin virgulă sau pe linii diferite)", 
                       placeholder="ex:\nGH97-18767C\n560610000000, 560610000001")

    add_col1, add_col2 = st.columns([1, 3])
    with add_col1:
        btn_add = st.button("Adaugă", type="primary")
    with add_col2:
        st.caption("Aliasurile se leagă de produs și sunt marcate `is_primary = false`. Notația științifică e suportată.")

    if btn_add and raw.strip():
        candidates = []
        for piece in re.split(r"[,;\n]+", raw):
            s = canon_sku(piece)
            if s:
                candidates.append(s)
        to_add = sorted(set(candidates) - set(row["all_skus"]))

        if not to_add:
            st.warning("Nimic de adăugat: toate SKU-urile sunt deja asociate.")
        else:
            ok, fail = [], []
            st.info(f"Încerc să adaug {len(to_add)} alias(uri)…")
            for sku in to_add:
                try:
                    resp = rpc_add_alias(product_id, sku)
                    if getattr(resp, "error", None):
                        fail.append((sku, str(resp.error)))
                    elif not getattr(resp, "data", None):
                        fail.append((sku, "RPC a răspuns fără date"))
                    else:
                        ok.append(sku)
                except Exception as e:
                    fail.append((sku, repr(e)))

            if ok:
                st.success(f"Adăugate: {', '.join(ok)}")
            if fail:
                st.error("Eșec la:")
                for sku, msg in fail:
                    st.write(f"- `{sku}` → {msg}")

            if ok and not fail:
                fetch_products.clear()
                st.rerun()

    st.markdown("---")

    # ===== ȘTERGERE ALIASURI =====
    st.markdown("### 🗑️ Șterge aliasuri")
    if not aliases:
        st.caption("Nu ai aliasuri de șters.")
    else:
        sel_to_remove = st.multiselect("Alege aliasurile de șters", options=aliases, placeholder="Selectează unul sau mai multe")
        danger = st.checkbox("Confirm că știu ce fac (nu pot șterge SKU principal)", value=False)
        colr1, colr2 = st.columns([1, 3])
        with colr1:
            btn_remove = st.button("Șterge selectate", disabled=not danger)
        with colr2:
            st.caption("Nu se va permite ștergerea SKU-ului principal. Operația afectează doar aliasurile.")

        if btn_remove:
            if not sel_to_remove:
                st.warning("Selectează măcar un alias.")
            else:
                ok, fail = [], []
                for sku in sel_to_remove:
                    try:
                        resp = rpc_remove_alias(product_id, sku)
                        if getattr(resp, "error", None):
                            fail.append((sku, str(resp.error)))
                        elif not getattr(resp, "data", None):
                            # dacă nu a returnat rând (poate nu exista)
                            fail.append((sku, "Nu s-a șters niciun rând (poate nu exista)"))
                        else:
                            ok.append(sku)
                    except Exception as e:
                        fail.append((sku, repr(e)))

                if ok:
                    st.success(f"Șterse: {', '.join(ok)}")
                if fail:
                    st.error("Eșec la:")
                    for sku, msg in fail:
                        st.write(f"- `{sku}` → {msg}")

                if ok and not fail:
                    fetch_products.clear()
                    st.rerun()
