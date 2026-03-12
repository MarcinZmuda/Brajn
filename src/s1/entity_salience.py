"""
===============================================================================
🎯 ENTITY SALIENCE v1.0 — Scoring, Co-occurrence & Placement Instructions
===============================================================================
Implementuje trzy brakujące elementy z Google Entity Patents:

1. SALIENCE SCORING (patent US9009192B1 / Google Research 2014)
   - Pozycja w tekście (encje na początku = wyższa salience)
   - Obecność w nagłówkach H1/H2 (sygnał strukturalny)
   - Rola gramatyczna (nsubj = podmiot → wyższa salience niż obj)
   - IDF boost (rzadsze encje = cenniejsze, patent US9679018B1)

2. CO-OCCURRENCE (patent US10235423B2 — metryka relatedness)
   - Pary encji w tym samym zdaniu (silna relacja)
   - Pary encji w tym samym akapicie (słabsza relacja)
   - Cross-source consistency (para u wielu konkurentów)

3. PLACEMENT INSTRUCTIONS (z dokumentu "Topical entities w SEO")
   - Primary entity → H1 + pierwszy akapit
   - Secondary entities → H2
   - Co-occurring pairs → ten sam akapit
   - Trójki E-A-V do jawnego opisania w tekście

Autor: BRAJEN Team
Data: 2025
===============================================================================
"""

import re
import math
from collections import Counter, defaultdict
from typing import List, Dict, Any, Optional, Tuple, Set
from dataclasses import dataclass, field

# v2.1: Import text cleaning to strip CSS before NER
try:
    try:
        from .entity_extractor import _clean_text_for_nlp
    except ImportError:
        from entity_extractor import _clean_text_for_nlp
except ImportError:
    _clean_text_for_nlp = None  # Fallback: no cleaning


# ================================================================
# 📦 DATA STRUCTURES
# ================================================================

@dataclass
class SalienceSignals:
    """Sygnały salience dla pojedynczej encji."""
    entity_text: str
    entity_type: str
    
    # Position signals
    avg_first_position: float = 1.0   # 0.0 = start, 1.0 = end (averaged over sources)
    early_mention_count: int = 0       # W ilu źródłach pojawia się w pierwszych 200 słowach
    
    # Heading signals
    in_h1_count: int = 0              # W ilu H1 się pojawia
    in_h2_count: int = 0              # W ilu H2 się pojawia
    heading_texts: List[str] = field(default_factory=list)  # Przykłady nagłówków
    
    # Grammatical role signals
    as_subject_count: int = 0          # Ile razy jest podmiotem (nsubj)
    as_object_count: int = 0           # Ile razy jest dopełnieniem (obj)
    subject_ratio: float = 0.0         # subject / (subject + object)
    
    # Frequency / distribution (z istniejących danych)
    frequency: int = 0
    sources_count: int = 0
    total_sources: int = 0
    
    # Computed salience
    salience_score: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "entity": self.entity_text,
            "type": self.entity_type,
            "salience": round(self.salience_score, 3),
            "signals": {
                "position": round(1.0 - self.avg_first_position, 3),  # Higher = earlier
                "early_mentions": self.early_mention_count,
                "in_headings": self.in_h1_count + self.in_h2_count,
                "subject_ratio": round(self.subject_ratio, 2),
                "distribution": f"{self.sources_count}/{self.total_sources}",
            },
            "heading_examples": self.heading_texts[:3],
        }


@dataclass
class CoOccurrencePair:
    """Para encji współwystępujących."""
    entity_a: str
    entity_b: str
    sentence_count: int = 0     # Razem w tym samym zdaniu
    paragraph_count: int = 0    # Razem w tym samym akapicie
    sources_count: int = 0      # W ilu źródłach współwystępują
    strength: float = 0.0       # Łączna siła powiązania
    sample_context: str = ""    # Przykładowe zdanie z obydwoma

    def to_dict(self) -> Dict:
        return {
            "entity_a": self.entity_a,
            "entity_b": self.entity_b,
            "sentence_co_occurrences": self.sentence_count,
            "paragraph_co_occurrences": self.paragraph_count,
            "sources_count": self.sources_count,
            "strength": round(self.strength, 3),
            "sample_context": self.sample_context,
        }


# ================================================================
# 🧠 1. SALIENCE SCORING
# ================================================================

def compute_salience(
    nlp,
    texts: List[str],
    urls: List[str],
    entities: List,       # ExtractedEntity objects
    h2_patterns: List[str] = None,
    h1_patterns: List[str] = None,
    main_keyword: str = "",
) -> List[SalienceSignals]:
    """
    Oblicza Entity Salience Score dla każdej encji.
    
    Czynniki (z Google Research 2014 + patent US9009192B1):
    1. Pozycja w tekście — encje bliżej początku = wyższa salience
    2. Obecność w H1/H2 — strukturalny boost
    3. Rola gramatyczna — podmiot (nsubj) > dopełnienie (obj)  
    4. Distribution — w ilu źródłach, IDF
    5. Keyword overlap — powiązanie z main keyword
    """
    if not entities or not texts:
        return []
    
    total_sources = len(texts)
    h2_patterns = h2_patterns or []
    h1_patterns = h1_patterns or []
    
    # Lowercase versions for matching (h2/h1 can be str or dict with "text" key)
    h2_lower = [
        (h["text"].lower() if isinstance(h, dict) else h.lower())
        for h in h2_patterns
    ]
    h1_lower = [
        (h["text"].lower() if isinstance(h, dict) else h.lower())
        for h in h1_patterns
    ]
    
    # Build entity lookup
    entity_signals: Dict[str, SalienceSignals] = {}
    for e in entities:
        key = e.text.lower()
        entity_signals[key] = SalienceSignals(
            entity_text=e.text,
            entity_type=e.type,
            frequency=e.frequency,
            sources_count=e.sources_count,
            total_sources=total_sources,
        )
    
    # ── PASS 1: Position + Grammatical role ──
    for src_idx, text in enumerate(texts):
        if not text or len(text) < 100:
            continue
        
        # v2.1: Clean text before NER
        text_clean = _clean_text_for_nlp(text) if _clean_text_for_nlp else text
        text_sample = text_clean[:50000]
        text_len = len(text_sample)
        
        # Track first positions per source
        first_positions_this_source: Dict[str, float] = {}
        
        try:
            doc = nlp(text_sample)
            
            for ent in doc.ents:
                key = ent.text.strip().lower()
                if key not in entity_signals:
                    continue
                
                signals = entity_signals[key]
                
                # Position (first occurrence in this source)
                if key not in first_positions_this_source:
                    position_ratio = ent.start_char / max(text_len, 1)
                    first_positions_this_source[key] = position_ratio
                    
                    # Early mention (first 200 words ≈ first 1500 chars)
                    if ent.start_char < 1500:
                        signals.early_mention_count += 1
                
                # Grammatical role (check root token of entity span)
                root_token = ent.root
                if root_token.dep_ in ("nsubj", "nsubj:pass"):
                    signals.as_subject_count += 1
                elif root_token.dep_ in ("obj", "iobj", "obl", "obl:arg"):
                    signals.as_object_count += 1
        
        except Exception as e:
            print(f"[SALIENCE] ⚠️ Error processing source {src_idx}: {e}")
            continue
        
        # Accumulate first positions
        for key, pos in first_positions_this_source.items():
            if key in entity_signals:
                signals = entity_signals[key]
                # Running average
                prev_count = signals.sources_count - 1 if signals.sources_count > 0 else 0
                old_total = signals.avg_first_position * prev_count
                signals.avg_first_position = (old_total + pos) / max(prev_count + 1, 1)
    
    # ── PASS 2: Heading presence ──
    for key, signals in entity_signals.items():
        # Check H1
        for h1 in h1_lower:
            if key in h1 or _fuzzy_match(key, h1):
                signals.in_h1_count += 1
                if h1 not in signals.heading_texts:
                    # Find original case version
                    idx = h1_lower.index(h1)
                    orig = h1_patterns[idx] if idx < len(h1_patterns) else h1
                    signals.heading_texts.append(orig["text"] if isinstance(orig, dict) else orig)
        
        # Check H2
        for i, h2 in enumerate(h2_lower):
            if key in h2 or _fuzzy_match(key, h2):
                signals.in_h2_count += 1
                if len(signals.heading_texts) < 5:
                    orig = h2_patterns[i] if i < len(h2_patterns) else h2
                    signals.heading_texts.append(orig["text"] if isinstance(orig, dict) else orig)
        
        # Subject ratio
        total_roles = signals.as_subject_count + signals.as_object_count
        if total_roles > 0:
            signals.subject_ratio = signals.as_subject_count / total_roles
    
    # ── PASS 3: Compute final salience score ──
    keyword_words = set()
    if main_keyword:
        keyword_words = {w.lower() for w in main_keyword.split() if len(w) > 2}
    
    for key, signals in entity_signals.items():
        score = 0.0
        
        # 1. Position score (0-0.25)
        # avg_first_position: 0.0 = very early, 1.0 = very late
        # Invert: earlier = higher score
        position_score = (1.0 - signals.avg_first_position) * 0.25
        score += position_score
        
        # 2. Heading boost (0-0.20)
        if signals.in_h1_count > 0:
            score += 0.15  # H1 = strong signal
        if signals.in_h2_count > 0:
            score += min(0.05, signals.in_h2_count * 0.02)  # H2 = moderate signal
        
        # 3. Grammatical role (0-0.15)
        # Subject > Object (Google: "Frodo zaniósł pierścień" → Frodo = 0.63)
        score += signals.subject_ratio * 0.15
        
        # 4. Distribution / IDF (0-0.25)
        if total_sources > 0:
            distribution = signals.sources_count / total_sources
            score += distribution * 0.20
            
            # IDF-like boost for rare but present entities
            if 0 < distribution < 0.5:
                idf_boost = -math.log(distribution + 0.01) * 0.02
                score += min(0.05, idf_boost)
        
        # 5. Early mention bonus (0-0.10)
        if signals.early_mention_count > 0:
            early_ratio = signals.early_mention_count / max(total_sources, 1)
            score += early_ratio * 0.10
        
        # 6. Keyword relevance (0-0.05)
        if keyword_words:
            entity_words = set(key.split())
            overlap = entity_words & keyword_words
            if overlap:
                score += 0.05
        
        signals.salience_score = min(1.0, score)
    
    # Sort by salience
    results = sorted(entity_signals.values(), key=lambda s: s.salience_score, reverse=True)
    
    print(f"[SALIENCE] ✅ Computed salience for {len(results)} entities "
          f"(top: {results[0].entity_text}={results[0].salience_score:.3f})" if results else "")
    
    return results


def _fuzzy_match(entity_key: str, heading: str) -> bool:
    """Sprawdza czy encja pasuje do nagłówka (uwzględnia polską fleksję — 3+ shared chars)."""
    if len(entity_key) < 3:
        return False
    # Check if any word in entity matches start of any word in heading (stem-like)
    entity_words = entity_key.split()
    heading_words = heading.split()
    for ew in entity_words:
        if len(ew) < 3:
            continue
        stem = ew[:max(3, len(ew) - 3)]  # Crude stem: cut last 3 chars for flection
        for hw in heading_words:
            if hw.startswith(stem):
                return True
    return False


# ================================================================
# 🔗 2. CO-OCCURRENCE EXTRACTION
# ================================================================

def extract_cooccurrence(
    nlp,
    texts: List[str],
    entities: List,          # ExtractedEntity objects
    max_pairs: int = 20,
    min_cooccurrences: int = 2,
) -> List[CoOccurrencePair]:
    """
    Wyciąga pary encji współwystępujących w zdaniach i akapitach.
    
    Patent US10235423B2: "Relatedness — jak często encja współwystępuje
    z innymi encjami danego typu na stronach internetowych."
    
    Dokument: "Encje pojawiające się w tym samym akapicie/zdaniu 
    tworzą silniejsze asocjacje niż encje oddalone o setki słów."
    """
    if not texts or not entities:
        return []
    
    # Entity keys set
    entity_keys = {e.text.lower() for e in entities}
    # Map key → original text
    entity_display = {e.text.lower(): e.text for e in entities}
    
    # Pair counters
    # key = tuple(sorted([entity_a, entity_b]))
    pair_data = defaultdict(lambda: {
        "sentence_count": 0,
        "paragraph_count": 0,
        "sources": set(),
        "contexts": [],
    })
    
    for src_idx, text in enumerate(texts):
        if not text or len(text) < 100:
            continue
        
        # v2.1: Clean text before NER
        text_clean = _clean_text_for_nlp(text) if _clean_text_for_nlp else text
        text_sample = text_clean[:50000]
        
        try:
            doc = nlp(text_sample)
            
            # ── Sentence-level co-occurrence ──
            for sent in doc.sents:
                sent_entities = set()
                for ent in sent.ents:
                    key = ent.text.strip().lower()
                    if key in entity_keys:
                        sent_entities.add(key)
                
                # All pairs in this sentence
                sent_list = sorted(sent_entities)
                for i in range(len(sent_list)):
                    for j in range(i + 1, len(sent_list)):
                        pair_key = (sent_list[i], sent_list[j])
                        pair_data[pair_key]["sentence_count"] += 1
                        pair_data[pair_key]["sources"].add(src_idx)
                        
                        # Save context (max 3)
                        if len(pair_data[pair_key]["contexts"]) < 3:
                            ctx = sent.text.strip()[:200]
                            if ctx and ctx not in pair_data[pair_key]["contexts"]:
                                pair_data[pair_key]["contexts"].append(ctx)
            
            # ── Paragraph-level co-occurrence ──
            # Split text into paragraphs (double newline or 150+ chars blocks)
            paragraphs = re.split(r'\n\s*\n|\r\n\s*\r\n', text_sample)
            
            for para in paragraphs:
                if len(para) < 50:
                    continue
                
                para_lower = para.lower()
                para_entities = set()
                
                for key in entity_keys:
                    if key in para_lower:
                        para_entities.add(key)
                
                para_list = sorted(para_entities)
                for i in range(len(para_list)):
                    for j in range(i + 1, len(para_list)):
                        pair_key = (para_list[i], para_list[j])
                        pair_data[pair_key]["paragraph_count"] += 1
        
        except Exception as e:
            print(f"[COOCCUR] ⚠️ Error processing source {src_idx}: {e}")
            continue
    
    # ── Build results ──
    results = []
    total_sources = len(texts)
    
    for (key_a, key_b), data in pair_data.items():
        total_co = data["sentence_count"] + data["paragraph_count"]
        if total_co < min_cooccurrences:
            continue
        
        # Strength score
        # Sentence co-occurrence = strong (weight 3)
        # Paragraph co-occurrence = moderate (weight 1)
        # Multi-source = boost
        strength = (data["sentence_count"] * 3.0 + data["paragraph_count"] * 1.0)
        source_count = len(data["sources"])
        if source_count >= 2:
            strength *= (1.0 + source_count * 0.2)
        
        # Normalize to 0-1 range (empirical cap at ~50)
        strength = min(1.0, strength / 50.0)
        
        results.append(CoOccurrencePair(
            entity_a=entity_display.get(key_a, key_a),
            entity_b=entity_display.get(key_b, key_b),
            sentence_count=data["sentence_count"],
            paragraph_count=data["paragraph_count"],
            sources_count=source_count,
            strength=strength,
            sample_context=data["contexts"][0] if data["contexts"] else "",
        ))
    
    results.sort(key=lambda x: x.strength, reverse=True)
    
    print(f"[COOCCUR] ✅ Found {len(results)} co-occurrence pairs "
          f"(returning top {min(max_pairs, len(results))})")
    
    return results[:max_pairs]


# ================================================================
# 📝 3. PLACEMENT INSTRUCTIONS
# ================================================================

def generate_placement_instructions(
    salience_data: List[SalienceSignals],
    cooccurrence_pairs: List[CoOccurrencePair],
    concept_entities: List[Dict] = None,
    relationships: List = None,
    main_keyword: str = "",
) -> Dict[str, Any]:
    """
    Generuje konkretne instrukcje rozmieszczenia encji dla writera.
    
    Dokument mówi:
    - "H1 musi zawierać encję główną"
    - "H2 powinny zawierać encje drugorzędne"  
    - "Pierwszy akapit — encja główna + 2–3 powiązane w pierwszych 100 słowach"
    - "Encje w tym samym akapicie tworzą silniejsze asocjacje"
    - "Trójki E-A-V stanowią semantyczny szkielet treści"
    """
    if not salience_data:
        return {"status": "NO_DATA", "instructions": ""}
    
    # ── Classify entities by role ──
    primary_entity = salience_data[0] if salience_data else None
    secondary_entities = salience_data[1:4]  # Top 2-4
    supporting_entities = salience_data[4:10]  # Top 5-10
    
    # Must-cover concepts
    must_concepts = []
    if concept_entities:
        must_concepts = [c.get("text", "") for c in concept_entities[:8]
                        if c.get("sources_count", 0) >= 2]
    
    # Top co-occurrence pairs
    strong_pairs = [p for p in cooccurrence_pairs if p.strength >= 0.2][:5]
    
    # Top relationships (E-A-V triples)
    top_relationships = []
    if relationships:
        for r in relationships[:5]:
            if hasattr(r, 'to_dict'):
                rd = r.to_dict()
            elif isinstance(r, dict):
                rd = r
            else:
                continue
            top_relationships.append(rd)
    
    # ── Build instruction text ──
    lines = []
    
    # 1. H1 + Title
    if primary_entity:
        lines.append(
            f"🎯 ENCJA GŁÓWNA (salience: {primary_entity.salience_score:.2f}): "
            f"\"{primary_entity.entity_text}\" ({primary_entity.entity_type})"
        )
        lines.append(
            f"   → MUSI być w tytule H1 i w pierwszym zdaniu artykułu"
        )
        # If there's a heading example from competitors
        if primary_entity.heading_texts:
            lines.append(
                f"   → Konkurencja używa w nagłówkach: {', '.join(primary_entity.heading_texts[:2])}"
            )
    
    # 2. First paragraph (100 words)
    first_para_entities = []
    if primary_entity:
        first_para_entities.append(primary_entity.entity_text)
    for se in secondary_entities[:2]:
        first_para_entities.append(se.entity_text)
    
    if first_para_entities:
        lines.append("")
        lines.append(
            f"📌 PIERWSZY AKAPIT (100 słów): Wprowadź te encje razem: "
            f"{', '.join(first_para_entities)}"
        )
        lines.append(
            f"   → Podaj jasną definicję/kontekst głównej encji i jej relacje z pozostałymi"
        )
    
    # 3. H2 entities
    if secondary_entities:
        lines.append("")
        h2_entities = [
            f"\"{se.entity_text}\" ({se.entity_type}, salience: {se.salience_score:.2f})"
            for se in secondary_entities
        ]
        lines.append(
            f"📋 ENCJE NA H2 (encje drugorzędne — każda powinna mieć swoją sekcję):"
        )
        for h2e in h2_entities:
            lines.append(f"   • {h2e}")
    
    # 4. Co-occurrence pairs
    if strong_pairs:
        lines.append("")
        lines.append(
            f"🔗 PARY WSPÓŁWYSTĘPUJĄCE (trzymaj w tym samym akapicie/zdaniu):"
        )
        for pair in strong_pairs:
            lines.append(
                f"   • \"{pair.entity_a}\" + \"{pair.entity_b}\" "
                f"(u konkurencji razem w {pair.sentence_count} zdaniach, "
                f"{pair.sources_count} źródłach)"
            )
    
    # 5. E-A-V Triples to describe
    if top_relationships:
        lines.append("")
        lines.append(
            f"🔺 RELACJE DO OPISANIA (trójki Encja→Atrybut→Wartość):"
        )
        for rel in top_relationships:
            subj = rel.get("subject", "?")
            verb = rel.get("verb", "?")
            obj = rel.get("object", "?")
            rtype = rel.get("type", "")
            lines.append(
                f"   • {subj} → {verb} → {obj} [{rtype}]"
            )
        lines.append(
            f"   → Opisz te relacje WPROST w tekście (np. \"X zapewnia Y\" zamiast ogólników)"
        )
    
    # 6. Concepts to weave in
    if must_concepts:
        lines.append("")
        lines.append(
            f"💡 POJĘCIA DO WPLECENIA (topical entities z konkurencji):"
        )
        lines.append(f"   {', '.join(must_concepts)}")
        lines.append(
            f"   → Użyj naturalnie w tekście, nie jako listę. "
            f"Pokrycie tych pojęć buduje topical authority."
        )
    
    # 7. Supporting entities (mention at least once)
    if supporting_entities:
        supporting_names = [se.entity_text for se in supporting_entities]
        lines.append("")
        lines.append(
            f"📎 ENCJE WSPIERAJĄCE (wspomnij przynajmniej raz w artykule):"
        )
        lines.append(f"   {', '.join(supporting_names)}")
    
    instruction_text = "\n".join(lines)
    
    # ── Build structured output ──
    return {
        "status": "OK",
        "primary_entity": primary_entity.to_dict() if primary_entity else None,
        "secondary_entities": [se.to_dict() for se in secondary_entities],
        "supporting_entities": [se.to_dict() for se in supporting_entities],
        "cooccurrence_pairs": [p.to_dict() for p in strong_pairs],
        "eav_triples": top_relationships,
        "first_paragraph_entities": first_para_entities,
        "h2_entities": [se.entity_text for se in secondary_entities],
        "must_cover_concepts": must_concepts,
        "placement_instruction": instruction_text,
    }
