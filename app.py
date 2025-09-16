# app.py — Admin aliasuri SKU (căutare în tabel, adăugare/ștergere; clear input după adăugare)
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
    # pregătim tabelul pentru selecție directă (checkbox pe rând)
    view_df = df[["name", "primary_sku"]].copy()
    view_df.insert(0, "selectează", False)

    # dacă există o selecție anterioară în session_state, o păstrăm
    if "selected_row_key" in st.session_state and st.session_state["selected_row_key"] in df.index:
        sel_idx = st.session_state["selected_row_key"]
        view_df.loc[sel_idx, "selectează"] = True

    edited = st.data_editor(
        view_df,
        key="results_editor",
        use_container_width=True,
        hide_index=False,
        height=360,
        column_config={
            "selectează": st.column_config.CheckboxColumn(required=False, help="Bifează un singur produs"),
            "name": st.column_config.TextColumn("Nume produs"),
            "primary_sku": st.column_config.TextColumn("SKU principal"),
        },
        disabled=["name", "primary_sku"],
    )

    # determinăm rândul selectat (impunem SINGLE select)
    selected_rows = [i for i, v in edited["selectează"].items() if v]
    if len(selected_rows) > 1:
        # dacă au bifat mai multe, păstrăm primul și curățăm restul în state la următorul rerun
        keep = selected_rows[0]
        st.warning("Te rog selectează un singur rând. Îl folosesc pe primul bifat.")
        st.session_state["selected_row_key"] = keep
    elif len(selected_rows) == 1:
        st.session_state["selected_row_key"] = selected_rows[0]
    else:
        st.session_state.pop("selected_row_key", None)

    # afișăm status selecție
    if "selected_row_key" in st.session_state:
        chosen_idx = st.session_state["selected_row_key"]
        chosen_row = df.loc[chosen_idx]
        product_id = chosen_row["product_id"]
        name = chosen_row["name"]
        primary = chosen_row["primary_sku"]
        aliases = sorted([s for s in chosen_row["all_skus"] if s != primary])
    else:
        product_id = name = primary = None
        aliases = []

with right:
    st.subheader("Detalii produs")
    if not product_id:
        st.info("Selectează un produs din tabelul din stânga.")
        st.stop()

    st.markdown(f"**Nume:** {name}")
    st.markdown(f"**SKU principal:** `{primary}`")

    st.markdown("**Aliasuri existente:**")
    if aliases:
        st.code(", ".join(aliases), language="text")
    else:
        st.info("Nu există aliasuri pentru acest produs.")

    st.markdown("---")

    # ===== ADĂUGARE ALIASURI =====
    st.markdown("### ➕ Adaugă aliasuri noi")
    raw = st.text_area(
        "SKU-uri de adăugat (separate prin virgulă sau pe linii diferite)",
        key="add_alias_input",
        placeholder="ex:\nGH97-18767C\n560610000000, 560610000001"
    )

    add_col1, add_col2 = st.columns([1, 3])
    with add_col1:
        btn_add = st.button("Adaugă", type="primary")
    with add_col2:
        st.caption("Aliasurile se leagă de produs și sunt marcate `is_primary = false`. Notația științifică e suportată.")

    if btn_add:
        raw_text = (st.session_state.get("add_alias_input") or "").strip()
        if not raw_text:
            st.warning("Introdu cel puțin un cod.")
        else:
            # parse + canonize + unice + exclude deja existente
            candidates = []
            for piece in re.split(r"[,;\n]+", raw_text):
                s = canon_sku(piece)
                if s:
                    candidates.append(s)
            to_add = sorted(set(candidates) - set(aliases) - {primary})

            if not to_add:
                st.warning("Nimic de adăugat: toate SKU-urile există deja (alias sau principal).")
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
                    # CLEAR INPUT după succes
                    st.session_state["add_alias_input"] = ""
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
