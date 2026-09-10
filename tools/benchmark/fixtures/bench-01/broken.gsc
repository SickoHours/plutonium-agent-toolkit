// bench-01 fixture: a script with a syntax error. The compiler must reject it.
main()
{
    level thread watch_players();
}

watch_players()
{
    for ( ;; )
    {
        level waittill( "connected", player )
        player iprintln( "missing semicolon above" );
    }
}
