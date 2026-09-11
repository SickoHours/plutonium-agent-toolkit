The T6 server script at `<FIXTURE>/face_glow.gsc` compiles, but a mod that carries it fails at
map load: one of its unqualified calls does not exist on the server script VM. Using the toolkit
and the knowledge data it ships (not by guessing), find that call, correct a copy of the script
(same file name) so every unqualified call resolves on the server VM while `face_glow_think` and
its message stay, and compile the corrected copy with the toolkit into a new directory under
`<RUN>/bench-05-builtin-wrong-vm/`. Report which call it was, which VM it does exist on with
which argument counts, and what the compile receipt proves and does not prove.
Save the toolkit's own answer verbatim: write the stdout document of `pat knowledge builtin setanimknob --json` to
`<RUN>/bench-05-builtin-wrong-vm/knowledge-lookup.json`. The score reads that file; a fix found by guessing leaves
no such file.
