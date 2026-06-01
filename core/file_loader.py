"""
core/file_loader.py — Source Text Loader and Searcher
======================================================
PURPOSE: Read .txt source files and extract ONLY the sections relevant to the
         searched entity. Avoids sending entire books to the API.

LOGIC:
  1. Receives an entity name and a .txt file path
  2. For large files (>2MB): uses the Dense Window Algorithm to find the chapter
  3. For small/medium files: extracts context windows around each mention
  4. Returns the relevant consolidated text, capped at MAX_CHARS_PER_SOURCE

USAGE:
  from core.file_loader import SourceLoader
  loader = SourceLoader()                   # Uses config.ACTIVE_TEMPLATE aliases
  loader = SourceLoader(template=my_tmpl)   # Uses custom template aliases
  text = loader.extract_relevant_text("Streptococcus pyogenes", Path("Murray.txt"))
"""

import re
from pathlib import Path
from typing import Optional, TYPE_CHECKING
import config
from core.logger import get_logger

if TYPE_CHECKING:
    from core.template_loader import Template

log = get_logger(__name__)


class SourceLoader:
    """
    Main class for loading and filtering text from .txt source files.
    Accepts an optional Template to use search aliases defined in YAML.
    """

    def __init__(self, template: Optional["Template"] = None):
        self._template = template

    def get_source_groups(self) -> dict[str, list[Path]]:
        """
        Returns a dictionary of source groups organized by type.
        Reads dynamically from the subdirectories of upload/ (config.SOURCES_BASE_DIR).

        Each subdirectory inside upload/ becomes one source group.
        All .txt files inside that subdirectory belong to the group.

        Returned structure:
            {
              "Books":    [Path(...upload/Books/Murray.txt), ...],
              "Notes":    [Path(...upload/Notes/lecture_01.txt), ...],
              "Articles": [Path(...upload/Articles/pmid_12345.txt)],
              ...
            }
        """
        groups: dict[str, list[Path]] = {}

        base = config.SOURCES_BASE_DIR
        if not base.exists():
            log.warning(f"Sources directory not found: {base}")
            log.warning("Add your books with: python kaosextract.py ingest my_book.pdf")
            return groups

        for subdir in sorted(base.iterdir()):
            if not subdir.is_dir() or subdir.name.startswith("."):
                continue

            group_files: list[Path] = []
            for f in subdir.rglob("*"):
                if f.is_file() and not f.name.startswith(".") and f.suffix.lower() in (".txt", ".md", ""):
                    group_files.append(f)

            if group_files:
                groups[subdir.name] = group_files
                log.debug(f"Group '{subdir.name}': {len(group_files)} file(s)")

        if not groups:
            log.warning(
                f"No source files found in {base}. "
                "Add books with: python kaosextract.py ingest my_book.pdf"
            )

        return groups

    def extract_relevant_text(
        self,
        entity_name: str,
        file_path: Path,
        context_chars: int = config.CONTEXT_WINDOW_CHARS,
        max_chars: int = config.MAX_CHARS_PER_SOURCE,
        is_transcript: bool = False,
    ) -> Optional[str]:
        """
        Extracts relevant sections from a .txt file for the given entity.

        Args:
            entity_name:   Name of the entity to search for (e.g. "Streptococcus pyogenes")
            file_path:     Path to the .txt file
            context_chars: Characters to extract around each mention
            max_chars:     Total character limit to return

        Returns:
            Relevant extracted text, or None if file not found / no mentions.
        """
        if not file_path.exists():
            log.error(f"File not found: {file_path}")
            return None

        log.debug(f"Reading: {file_path.name}")
        try:
            text = file_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            log.error(f"Error reading {file_path.name}: {e}")
            return None

        # Repair OCR-spaced text (e.g. 'S tr e p to c o c c u s' → 'Streptococcus')
        text = self._fix_ocr_text(text)

        # Generate search variants for the entity name
        search_terms = self._get_search_terms(entity_name, is_transcript)

        # Find all positions where the entity appears in the text
        positions = self._find_positions(text, search_terms)

        if not positions:
            log.debug(f"'{entity_name}' not found in {file_path.name}")
            return None

        log.debug(f"'{entity_name}': {len(positions)} mention(s) in {file_path.name}")

        # Large textbooks (>2MB): use Dense Window Algorithm to capture
        # the full chapter instead of scattered fragments.
        if file_path.stat().st_size > config.DENSE_WINDOW_SIZE_THRESHOLD:
            extracted = self._extract_dense_chapter(text, entity_name, search_terms, max_chars=360_000)
            return extracted

        # Small/medium files: extract windows around each mention
        extracted = self._extract_windows(text, positions, context_chars, max_chars)
        return extracted

    def extract_from_group(
        self, entity_name: str, files: list[Path], is_transcript: bool = False
    ) -> str:
        """
        Extracts relevant text from multiple files and concatenates them.
        Useful for groups like Notes, Lectures, or Other that have several files.

        Returns:
            Combined text from all files with mentions, or not-found message.
        """
        parts: list[str] = []

        for f in files:
            text = self.extract_relevant_text(entity_name, f, is_transcript=is_transcript)
            if text:
                parts.append(f"\n\n{'='*60}\nSOURCE: {f.name}\n{'='*60}\n{text}")

        if not parts:
            return "FUENTE_SIN_INFORMACIÓN_RELEVANTE"

        combined = "\n".join(parts)

        if len(combined) > config.MAX_CHARS_PER_SOURCE:
            combined = combined[:config.MAX_CHARS_PER_SOURCE]
            combined += "\n\n[TEXT TRUNCATED — CHARACTER LIMIT REACHED]"

        return combined

    # ── Private methods ───────────────────────────────────────────────────────

    def _fix_ocr_text(self, text: str) -> str:
        """
        Repairs OCR-spaced text where the scanner separated individual letters.
        Example: 'S tr e p to c o c c u s' → 'Streptococcus'
        Only collapses blocks of 4+ consecutive 1-3 letter groups.
        """
        pattern = re.compile(
            r'(?<![\w])'
            r'((?:[A-Za-záéíóúüñÁÉÍÓÚÜÑ]{1,3} ){3,}[A-Za-záéíóúüñÁÉÍÓÚÜÑ]{1,3})'
            r'(?![\w])'
        )
        return pattern.sub(lambda m: m.group(0).replace(' ', ''), text)

    def _extract_dense_chapter(self, text: str, entity_name: str, search_terms: list[str], max_chars: int) -> str:
        """
        Dense Window Algorithm for large books (>2MB).

        Extracts the chapter dedicated to the entity, avoiding bibliography
        sections that inflate mention scores with false positives.

        PROCESS:
        1. Split book into 100k-char overlapping blocks
        2. Score each block: mentions × 10 + density_bonus - bibliography_penalty
        3. Search for chapter heading containing the entity name
        4. Extract up to max_chars from chapter start
        """
        total = len(text)
        block_size = 100_000
        step = 50_000
        lower_terms = [t.lower() for t in search_terms]
        text_lower = text.lower()

        # Patterns indicating bibliography sections (not clinical content)
        BIBLIO_PATTERNS = [
            r'\d{4}[;:]\d+',          # year:pages citation (e.g. 2008;6:32)
            r'et al\.',                # references with "et al."
            r'n engl j med',           # New England Journal of Medicine
            r'j infect dis',           # Journal of Infectious Diseases
            r'clin infect dis',        # Clinical Infectious Diseases
            r'bibliograf[íi]a',        # bibliography header (Spanish)
            r'referencias',            # references header
            r'selected readings',      # references (English)
        ]
        biblio_compiled = [re.compile(p, re.IGNORECASE) for p in BIBLIO_PATTERNS]

        # ── Step 1: Score all blocks ──────────────────────────────────────────
        block_scores = []

        for block_start in range(0, total, block_size // 2):
            block_end = min(block_start + block_size, total)
            block_text = text_lower[block_start:block_end]
            block_text_original = text[block_start:block_end]

            mention_count = sum(block_text.count(t) for t in lower_terms)

            if mention_count == 0:
                block_scores.append({'start': block_start, 'end': block_end,
                                     'score': 0, 'mentions': 0})
                continue

            # ── Bibliography penalty ──────────────────────────────────────────
            biblio_hits = sum(len(p.findall(block_text_original)) for p in biblio_compiled)
            biblio_penalty = min(biblio_hits * 3, mention_count * 8)

            # ── Density bonus ─────────────────────────────────────────────────
            density_bonus = 0
            for term in lower_terms:
                positions_in_block = []
                start_pos = 0
                while True:
                    pos = block_text.find(term, start_pos)
                    if pos == -1:
                        break
                    positions_in_block.append(pos)
                    start_pos = pos + 1
                if len(positions_in_block) >= 3:
                    density_bonus += min(mention_count, 10) * 0.5
                elif len(positions_in_block) >= 2:
                    density_bonus += min(mention_count, 5) * 0.3

            score = (mention_count * 10) + density_bonus - biblio_penalty

            block_scores.append({
                'start': block_start,
                'end': block_end,
                'score': score,
                'mentions': mention_count,
                'biblio_hits': biblio_hits,
            })

        if not block_scores:
            return ""

        # ── Step 2: Best block with real content ──────────────────────────────
        best_block = max(block_scores, key=lambda x: x['score'])

        if best_block['score'] <= 0:
            non_zero = [b for b in block_scores if b['mentions'] > 0]
            if not non_zero:
                log.debug(f"'{entity_name}': No mentions found in dense analysis.")
                return ""
            best_block = max(non_zero, key=lambda x: x['mentions'])
            log.debug(f"'{entity_name}': All blocks look like bibliography. Using fallback.")

        log.debug(
            f"'{entity_name}': Best block at pos {best_block['start']:,}, "
            f"{best_block['mentions']} mentions, score={best_block['score']:.1f}"
        )

        # ── Step 3: Search for dedicated chapter heading ──────────────────────
        entity_words = entity_name.lower().split('|')[0].strip().split()
        entity_significant = [w for w in entity_words if len(w) >= 4]

        dedicated_chapter_start = None

        if entity_significant:
            heading_pattern = re.compile(
                r'(?:cap[íi]tulo\s+\d+|chapter\s+\d+)[^\n]{0,150}',
                re.IGNORECASE
            )
            best_score = 0
            best_match = None

            for match in heading_pattern.finditer(text_lower):
                heading = match.group()
                score = 0
                for w in entity_significant:
                    if re.search(r'\b' + re.escape(w) + r'\b', heading):
                        score += 1
                if score > best_score:
                    best_score = score
                    best_match = match

            if best_match and best_score > 0:
                dedicated_chapter_start = best_match.start()
                log.debug(
                    f"'{entity_name}': Dedicated chapter at pos {dedicated_chapter_start:,}: "
                    f"{best_match.group()[:80]!r} (Score: {best_score}/{len(entity_significant)})"
                )

        # ── Step 4: Select extraction point ──────────────────────────────────
        if dedicated_chapter_start is not None:
            macro_chunk_start = dedicated_chapter_start
        else:
            best_block_fb = max(block_scores, key=lambda x: x['score'])
            if best_block_fb['score'] <= 0:
                non_zero = [b for b in block_scores if b['mentions'] > 0]
                if not non_zero:
                    return ""
                best_block_fb = max(non_zero, key=lambda x: x['mentions'])
            macro_chunk_start = max(0, best_block_fb['start'] - 50_000)

        # Extract final window of max_chars from chapter start
        window_size = min(max_chars, 400_000)
        final_start = macro_chunk_start
        final_end = min(final_start + window_size, total)
        extracted = text[final_start:final_end]

        log.debug(
            f"Chapter extracted: pos {final_start:,} to {final_end:,} "
            f"(len: {len(extracted):,} chars)"
        )
        return extracted

    def _extract_windows(self, text: str, positions: list[int], context_chars: int, max_chars: int) -> str:
        """
        Extracts context windows around each found position.
        Used for small/medium files.
        """
        extracted_chunks = []
        current_total_chars = 0

        unique_positions = []
        if positions:
            unique_positions.append(positions[0])
            for p in positions[1:]:
                if p - unique_positions[-1] > context_chars // 2:
                    unique_positions.append(p)

        for pos in unique_positions:
            if current_total_chars >= max_chars:
                break

            start = max(0, pos - context_chars // 2)
            end = min(len(text), pos + context_chars // 2)

            chunk = text[start:end]
            extracted_chunks.append(f"... {chunk} ...")
            current_total_chars += len(chunk)

        combined = "\n\n".join(extracted_chunks)

        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n\n[TEXT TRUNCATED — CHARACTER LIMIT REACHED]"

        return combined

    def _get_search_terms(self, entity_name: str, is_transcript: bool = False) -> list[str]:
        """
        Generates variants of the entity name to broaden the search.
        Supports multiple names/synonyms separated by '|'.
        Example: "Clostridium difficile|Peptoclostridium difficile"

        If a Template is active, uses aliases defined in the YAML.
        If no Template, the search is by name variants only.
        """
        terms = []
        aliases = [alias.strip() for alias in entity_name.split('|') if alias.strip()]

        for alias in aliases:
            terms.append(alias)
            parts = alias.split()

            # Genus abbreviation (e.g. "S. aureus")
            if len(parts) >= 2:
                terms.append(f"{parts[0][0]}. {' '.join(parts[1:])}")

            # Uppercase variant (some books use ALL CAPS)
            terms.append(alias.upper())

        # Aliases from active Template YAML (if available)
        if self._template is not None:
            terms.extend(self._template.get_aliases_for_entity(entity_name))

        return list(dict.fromkeys(terms))  # Remove duplicates, preserve order

    def _find_positions(self, text: str, search_terms: list[str]) -> list[int]:
        """
        Finds all character positions where any search term appears.
        Case-insensitive. Returns sorted, deduplicated positions.
        """
        positions = []
        text_lower = text.lower()

        for term in search_terms:
            term_lower = term.lower()
            start = 0
            while True:
                pos = text_lower.find(term_lower, start)
                if pos == -1:
                    break
                positions.append(pos)
                start = pos + 1

        if not positions:
            return []

        positions.sort()
        filtered = [positions[0]]
        for pos in positions[1:]:
            if pos - filtered[-1] > 500:  # Minimum 500 chars separation
                filtered.append(pos)

        return filtered
