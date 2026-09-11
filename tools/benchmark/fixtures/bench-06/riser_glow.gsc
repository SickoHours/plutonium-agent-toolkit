// bench-06 fixture: the only script of a mod that passed compile and readback and then
// failed at map load with the console slice beside this file.

main()
{
    registerclientfield( "actor", "bench_riser_glow", 1, 1, "int" );
    level thread riser_glow_watch();
}

riser_glow_watch()
{
    for ( ;; )
    {
        level waittill( "connected", player );
        player thread riser_glow_think();
    }
}

riser_glow_think()
{
    self endon( "disconnect" );
    for ( ;; )
    {
        self waittill( "spawned_player" );
        self iprintln( "^5riser glow armed" );
    }
}
