// bench-05 fixture: a server script that compiles cleanly and fails at map load.
// One unqualified call in it does not exist on the server script VM; the toolkit's
// knowledge data says which, and on which VM it does exist.

main()
{
    level thread face_glow_watch();
}

face_glow_watch()
{
    for ( ;; )
    {
        level waittill( "connected", player );
        player thread face_glow_think();
    }
}

face_glow_think()
{
    self endon( "disconnect" );
    self waittill( "spawned_player" );
    self setanimknob( "face_glow", 1, 0.2, 0 );
    self iprintln( "^3face glow armed" );
}
