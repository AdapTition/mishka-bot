# Client requirements (Mishka the Scribbler)

Gathered in conversation with the client bot on 2026-10-29. The client's documents and chat are in Ukrainian,
so names of places and documents are kept in Ukrainian with a translation where useful.

## Context
- The animals wrote a pile of advice documents (PDF, Word, TXT) and nobody can find their way around them.
- The forest has eight mittens, each one a separate HOA.
- The initial documents are in the "Forest Archive" (`data/archive`). They are standard documents with no sender.

## Confirmed by the client
1. The bot works only in Telegram private messages; group chats are not needed.
2. An animal asks, and the bot answers from the advice in the documents and **names the source document**.
3. Advice can be for the whole forest, for a part of the forest, or for a single mitten. Everyone can see all documents, but not all advice fits everyone (e.g. dues for Under the Oak).
4. The scope of a piece of advice is sometimes named explicitly in the document ("under the spruces" means the coniferous forest) and sometimes unclear (as in the "Малина" file). In that case the bot **asks the sender instead of guessing**.
5. Animals send the bot new documents themselves, in PDF, Word and TXT. They do not send photos of documents.
6. The bot does not need to know who is asking. The animal names the mitten in the question if it matters.
7. Advice priority: for the mitten first, then for the forest part, then for the whole forest. General advice may be mentioned additionally.
8. "Під вербою" (Under the Willow) belongs to both the deciduous forest and the river. The bot shows both pieces of advice with their sources, or clarifies where exactly the animal will be looking.
9. A newer version of the same document for the same place **replaces the old one**: animals see only the new one.
10. Any animal can send documents, there are no admins. The bot **remembers and names the sender**, so it is clear whom to thank and whom to ask. For archive documents only the document itself is named.

## Forest map (from the "Карта лісу" document)
| Mitten | Forest part |
|---|---|
| Під ялиною (Under the Spruce) | coniferous forest |
| У соснах (In the Pines) | coniferous forest |
| Біля мурашника (By the Anthill) | coniferous forest |
| Під дубом (Under the Oak) | deciduous forest |
| У ліщині (In the Hazel) | deciduous forest |
| Під вербою (Under the Willow) | deciduous forest + by the river |
| Біля бобрової греблі (By the Beaver Dam) | by the river |
| На узліссі (At the Forest Edge) | no part |

## Developer decisions (Mishka asked me to decide and report back)
- **Who is asking.** No registration. If the answer depends on the mitten and it is not named, the bot asks and offers buttons with the mittens. If an animal is named in the question ("How much does Bunny pay?"), the place is determined from the documents.
- **Conversation.** The bot remembers the last 6 turns (30 minutes) and understands follow-ups ("and in winter?"). Greetings, thanks and comments are not treated as questions.
- **No answer.** The bot answers only from the documents. If there is no advice, it honestly says so and invents nothing.
- **Date.** The bot knows today's date and weekday (Europe/Kyiv) and uses them for "today" or "tomorrow". It does not invent what it cannot know (weather, state of the dam), but reminds of the rule.
- **Deletion.** An animal can delete only a document it sent itself. Archive documents cannot be deleted.
- **Scans.** PDFs without a text layer are recognised via OCR (Tesseract, Ukrainian).
