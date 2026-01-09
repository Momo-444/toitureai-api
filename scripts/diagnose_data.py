import os
from supabase import create_client, Client

url = "https://pnvnipgtydhlhgrjwzvu.supabase.co"
key = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InBudm5pcGd0eWRobGhncmp3enZ1Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MzYxNTQxMCwiZXhwIjoyMDc5MTkxNDEwfQ.Nr6riK8lsptwjBmFya25py3i-KGbdOJ91L26t-wv_78"

supabase: Client = create_client(url, key)

print("--- DIAGNOSTIC DASHBOARD ---")
print("\n[1] CHECKING DEVIS (Decembre)")
try:
    # Fetch all devis to see statuses and dates
    response = supabase.table("devis").select("*").execute()
    devis_list = response.data
    
    print(f"Total Devis found: {len(devis_list)}")
    for d in devis_list:
        print(f"  - ID: {d.get('numero')} | Date: {d.get('date_creation')} | Statut: '{d.get('statut')}' | TTC: {d.get('montant_ttc')}")

    # Check Total Revenue calc logic locally
    valid_statuses = ['payes', 'paye', 'signe', 'signé', 'accepte', 'accepté', 'signé']
    total_rev = sum(d.get('montant_ttc', 0) for d in devis_list if d.get('statut') in valid_statuses)
    print(f"\nCalculated Total Revenue (Signed+Paid): {total_rev} €")
    
    # Check December specific
    dec_rev = 0
    for d in devis_list:
        date = d.get('date_creation')
        if date and '2025-12' in date:
             if d.get('statut') in valid_statuses:
                 dec_rev += d.get('montant_ttc', 0)
                 print(f"    -> MATCH DEC: {d.get('montant_ttc')} (Statut: {d.get('statut')})")
             else:
                 print(f"    -> SKIP DEC: {d.get('montant_ttc')} (Statut: {d.get('statut')} NOT IN VALID LIST)")
    print(f"Calculated December Revenue: {dec_rev} €")

except Exception as e:
    print(f"Error fetching devis: {e}")

print("\n[2] CHECKING LEADS (Hot Logic)")
try:
    response = supabase.table("leads").select("*").order("created_at", desc=True).limit(10).execute()
    leads = response.data
    for l in leads:
        is_hot_flag = l.get('lead_chaud')
        score = l.get('score_qualification')
        clicks = l.get('email_clic_count')
        statut = l.get('statut')
        print(f"  - {l.get('nom')} {l.get('prenom')} | Statut: {statut} | Flag Hot: {is_hot_flag} | Score: {score} | Clicks: {clicks}")

except Exception as e:
    print(f"Error fetching leads: {e}")
