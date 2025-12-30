-- ============================================
-- MIGRATION: Ajouter les colonnes pour ToitureAI API Python
-- Executez ce script dans Supabase SQL Editor
-- ============================================

-- 1) Colonnes de tracking pour la table leads
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS email_ouvert BOOLEAN DEFAULT FALSE;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS email_ouvert_count INTEGER DEFAULT 0;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS email_clic_count INTEGER DEFAULT 0;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS lead_chaud BOOLEAN DEFAULT FALSE;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS derniere_interaction TIMESTAMPTZ;

-- 2) Colonnes IA pour la table leads
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS score_qualification INTEGER DEFAULT 0;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS urgence TEXT DEFAULT 'faible';
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS recommandation_ia TEXT;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS segments TEXT[];

-- 3) Colonnes supplementaires pour leads
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS budget INTEGER;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS delai TEXT;
ALTER TABLE public.leads ADD COLUMN IF NOT EXISTS contraintes TEXT;

-- 4) Colonnes supplementaires pour devis
ALTER TABLE public.devis ADD COLUMN IF NOT EXISTS date_signature TIMESTAMPTZ;
ALTER TABLE public.devis ADD COLUMN IF NOT EXISTS docuseal_submission_id TEXT;

-- 5) Table error_logs
CREATE TABLE IF NOT EXISTS public.error_logs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  workflow TEXT,
  node TEXT,
  message TEXT,
  details JSONB,
  execution_id TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.error_logs ENABLE ROW LEVEL SECURITY;

-- 6) Policies pour service_role (bypass RLS)

-- Leads
DROP POLICY IF EXISTS "Service role full access leads" ON public.leads;
CREATE POLICY "Service role full access leads"
ON public.leads FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Devis
DROP POLICY IF EXISTS "Service role full access devis" ON public.devis;
CREATE POLICY "Service role full access devis"
ON public.devis FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- Error logs
DROP POLICY IF EXISTS "Service role full access error_logs" ON public.error_logs;
CREATE POLICY "Service role full access error_logs"
ON public.error_logs FOR ALL
TO service_role
USING (true)
WITH CHECK (true);

-- ============================================
-- FIN DE LA MIGRATION
-- Redemarrez votre serveur Python apres execution
-- ============================================
