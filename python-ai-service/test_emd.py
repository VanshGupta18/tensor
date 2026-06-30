emd_pct = 2
emd_cap = 50000000
ec_amt = 52546.85
ec_denom = "lakhs"

ec_lakhs = ec_amt if ec_denom in ("lakhs", "lakh", "") else ec_amt * 100
expected_lakhs = emd_pct / 100 * ec_lakhs
expected_inr = expected_lakhs * 100000
ratio = abs(expected_inr - emd_cap) / max(expected_inr, emd_cap, 1)
print(ratio)
