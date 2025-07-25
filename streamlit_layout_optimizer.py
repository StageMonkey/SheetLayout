import streamlit as st
from fractions import Fraction
import re
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from rectpack import newPacker
import pandas as pd
import io

# --- Parsing helpers ---
def rounded(value):
    return round(value + 1e-6, 2)  # Avoid .99 issues
    
def parse_fractional_inches(value: str) -> float:
    value = value.strip()
    if ' ' in value:
        whole, frac = value.split()
        return float(whole) + float(Fraction(frac))
    elif '/' in value:
        return float(Fraction(value))
    else:
        return float(value)  # Accepts decimals like 12.5

def parse_cut_line(line: str):
    pattern = r'(?:([\d]+)\s*@\s*)?([0-9\/\.\s]+)\s*[xX]\s*([0-9\/\.\s]+)(?:\s+([LW]))?'
    match = re.match(pattern, line.strip())
    if not match:
        raise ValueError(f"Invalid format: '{line}'")
    
    qty_str, raw_length, raw_width, grain = match.groups()
    quantity = int(qty_str) if qty_str else 1
    length = parse_fractional_inches(raw_length)
    width = parse_fractional_inches(raw_width)
    grain = grain.upper() if grain else None
    
    return {"length": length, "width": width, "grain": grain, "quantity": quantity}

def parse_cut_list(cut_list_text: str):
    lines = cut_list_text.strip().split('\n')
    pieces = []
    for line in lines:
        if line.strip():
            try:
                piece = parse_cut_line(line)
                for _ in range(piece.get("quantity", 1)):
                    pieces.append({k: piece[k] for k in ["length", "width", "grain"]})
            except ValueError as e:
                st.warning(f"Skipping line: {e}")
    return pieces

# --- Packing logic ---
def run_layout_optimizer(cuts, sheet_length, sheet_width, kerf, grain_direction):
    scale = 100
    def scale_up(v): return int(round(v * scale))

    bin_width = scale_up(sheet_width)
    bin_height = scale_up(sheet_length)

    packer = newPacker(rotation=True)
    for _ in range(100):
        packer.add_bin(bin_width, bin_height)

    for i, cut in enumerate(cuts):
        w = scale_up(cut['width'] + kerf)
        h = scale_up(cut['length'] + kerf)
        grain = cut.get('grain')

        if grain == "L" and cut['width'] > cut['length']:
            w, h = h, w
        elif grain == "W" and cut['length'] > cut['width']:
            w, h = h, w

        packer.add_rect(w, h, rid=i)

    packer.pack()
    return packer

# --- Visualization ---
def draw_layout(packer, cuts, sheet_length, sheet_width, kerf):
    for i, abin in enumerate(packer):
        fig, ax = plt.subplots(figsize=(10, 6))
        ax.set_title(f"Sheet {i + 1}")
        ax.set_xlim(0, sheet_width)
        ax.set_ylim(0, sheet_length)
        ax.set_aspect('equal')
        ax.invert_yaxis()

        ax.add_patch(patches.Rectangle((0, 0), sheet_width, sheet_length,
                                       linewidth=1, edgecolor='black', facecolor='none'))

        for rect in abin:
            x = rect.x
            y = rect.y
            w = rect.width
            h = rect.height
            rid = rect.rid

            cut = cuts[rid]

            # Convert back to inches
            disp_w = rounded((w / 100) - kerf)
            disp_h = rounded((h / 100) - kerf)
            disp_x = x / 100
            disp_y = y / 100

            # Infer rotation
            original_w = cut['width']
            original_h = cut['length']
            rotated = not (
                abs(disp_w - original_w) < 0.01 and
                abs(disp_h - original_h) < 0.01
            )

            color = "#d3e5ff" if not rotated else "#ffa07a"

            ax.add_patch(patches.Rectangle(
                (disp_x, disp_y), disp_w, disp_h,
                edgecolor='black', facecolor=color, linewidth=1.5
            ))

            label = f"{disp_w:.2f}\" x {disp_h:.2f}\""
            if cut.get("grain"):
                label += f" ({cut['grain']})"
            ax.text(disp_x + 0.2, disp_y + 0.2, label, fontsize=8, verticalalignment='top')

        st.pyplot(fig)

# --- CSV Export ---
def generate_layout_summary(packer, cuts, kerf):
    rows = []
    for sheet_num, abin in enumerate(packer):
        for rect in abin:
            x = rect.x
            y = rect.y
            w = rect.width
            h = rect.height
            rid = rect.rid

            cut = cuts[rid]

            width = round((w / 100) - kerf, 4)
            height = round((h / 100) - kerf, 4)

            rotated = not (
                abs(width - cut['width']) < 0.01 and
                abs(height - cut['length']) < 0.01
            )

            rows.append({
                "Sheet": sheet_num + 1,
                "X (in)": round(x / 100, 4),
                "Y (in)": round(y / 100, 4),
                "Width (in)": width,
                "Height (in)": height,
                "Rotated": rotated,
                "Grain Pref": cut.get("grain") or "Any"
            })

    return pd.DataFrame(rows)

# --- Streamlit UI ---
st.title("📐 Plywood Layout Optimizer")

sheet_length = st.text_input("Sheet Length (inches)", "96")
sheet_width = st.text_input("Sheet Width (inches)", "48")
kerf = st.text_input("Kerf Size (inches)", "1/8")
grain_direction = st.selectbox("Sheet Grain Runs:", ["Lengthwise", "Widthwise"])

st.markdown("Enter one piece per line like `24 x 36 L` or `12 x 12`")
cut_list_input = st.text_area("Cut List", height=200)

if st.button("Optimize Layout"):
    try:
        sheet_L = parse_fractional_inches(sheet_length)
        sheet_W = parse_fractional_inches(sheet_width)
        kerf_val = parse_fractional_inches(kerf)
        cuts = parse_cut_list(cut_list_input)

        packer = run_layout_optimizer(cuts, sheet_L, sheet_W, kerf_val, grain_direction)

        st.success(f"✅ Used {len(list(packer))} sheet(s)")

        draw_layout(packer, cuts, sheet_L, sheet_W, kerf_val)

        df = generate_layout_summary(packer, cuts, kerf_val)
        st.subheader("📋 Layout Summary Table")
        st.dataframe(df)

        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Download CSV",
            data=csv_buffer.getvalue(),
            file_name="layout_summary.csv",
            mime="text/csv"
        )

    except Exception as e:
        st.error(f"Error: {e}")
