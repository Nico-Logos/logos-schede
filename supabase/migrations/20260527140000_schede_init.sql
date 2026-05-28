-- =============================================================================
-- Migration: 20260527140000_schede_init
-- Progetto: logos-flow-prod (lo stesso di Flow — Schede ci si appoggia).
-- Scopo:    tabella `schede` (metadati + JSON estratto/redazionale + path PDF)
--           e bucket Storage privato `schede-pdf`.
--
-- Auth: per il primo deploy Schede NON ha auth Supabase → l'app scrive con
-- service_role (bypassa la RLS). `generata_da` resta NULL finché non integriamo
-- l'auth di Flow. La RLS è comunque ABILITATA senza policy: così la tabella è
-- raggiungibile SOLO via service_role (anon/authenticated non vedono nulla).
-- =============================================================================

create table public.schede (
  id                    uuid primary key default gen_random_uuid(),
  titolo                text not null,
  ente                  text,
  dati_estratti         jsonb not null,   -- JSON del passo 2 (dati grezzi del bando)
  testi_redazionali     jsonb not null,   -- JSON del passo 3A (scheda_logos)
  pdf_path              text,             -- path dentro il bucket schede-pdf (es. "<uuid>.pdf")
  url_decreto_originale text,
  generata_da           uuid references public.profiles(id),  -- NULL per ora
  created_at            timestamptz default now()
);

comment on table public.schede is 'Schede bando generate dal tool Logos Schede. Scrittura via service_role (no auth Schede al primo deploy); RLS per ruolo quando si integra con Flow.';

create index idx_schede_created_at on public.schede (created_at desc);

-- RLS abilitata senza policy → accesso solo service_role (bypass). Policy per
-- ruolo in un secondo momento (integrazione con l'auth di Flow).
alter table public.schede enable row level security;

-- Bucket Storage privato per i PDF generati.
insert into storage.buckets (id, name, public)
values ('schede-pdf', 'schede-pdf', false)
on conflict (id) do nothing;
