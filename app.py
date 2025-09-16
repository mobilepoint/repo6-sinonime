import re
from decimal import Decimal, InvalidOperation

import pandas as pd
import streamlit as st
from supabase import create_client

# =========================
#   CONFIG
# =========================
st.set_page_config(page_title="Admin aliasuri SKU", layout="wide")
st.title("Admin aliasuri SKU (Supabase)")

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
    """curăță spații, convertește 5.6061E+11 -> 560610000000"""
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
    # normalizare all_skus -> list
    if "all_skus" in df.columns:
        df["all_skus"] = df["all_skus"].apply(lambda v: v if isinstance(v, list) else [])
    return df

def add_alias(product_id: str, new_sku: str):
    """Apelează RPC-ul public.add_alias_sku."""
    return client.rpc("add_alias_sku", {"p_product_id": product_id, "p_sku": new_sku}).execute()

# =========================
#   UI
# =========================
search = st.text_input("Caută produs după nume", placeholder="ex: iPhone 11, G935 GOLD, etc.")
df = fetch_products(search.strip() or None)

if df.empty:
    st.info("N-am găsit produse pentru criteriul de căutare.")
    st.stop()

# listă selectabilă
left, right = st.columns([2, 3], gap="large")

with left:
    st.subheader("Rezultate")
    # tabel scurt
    st.dataframe(df[["name", "primary_sku"]], use_container_width=True, hide_index=True, height=300)

    # selector produs
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

    st.markdown("**Aliasuri existente:**")
    if aliases:
        st.code(", ".join(aliases), language="text")
    else:
        st.info("Nu există aliasuri pentru acest produs.")

    st.markdown("---")
    st.markdown("**Adaugă aliasuri noi** (separate prin virgulă sau pe linii diferite)")
    raw = st.text_area("SKU-uri de adăugat", placeholder="ex:\nGH97-18767C\n560610000000, 560610000001")

    colb1, colb2 = st.columns([1, 3])
    with colb1:
        btn = st.button("➕ Adaugă", type="primary")
    with colb2:
        st.caption("La insert, aliasurile se vor lega de produs și vor fi marcate `is_primary = false`.")

    if btn and raw.strip():
        # parse + canonize + unice + exclude deja existente
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
            for sku in to_add:
                try:
                    resp = add_alias(product_id, sku)
                    # resp.data conține rândul inserat/upsertat
                    ok.append(sku)
                except Exception as e:
                    fail.append((sku, str(e)))

            if ok:
                st.success(f"Adăugate: {', '.join(ok)}")
            if fail:
                st.error("Eșec la: " + "; ".join([f"{s} ({msg})" for s, msg in fail]))

            # refresh cache și UI
            fetch_products.clear()
            st.rerun()
