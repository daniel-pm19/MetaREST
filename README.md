# MetaREST


El modelo de generación (Sonnet 5.5) y el de verificación (Haiku 5.5);
la salida estructurada con output_config.format en lugar de forzar una herramienta, y por eso existe wire.py;
el nivel de razonamiento (effort), max_tokens con streaming, el respaldo del servidor cuando el modelo se niega a responder, el máximo de 20 MRs por run, el idioma del prompt, y el timeout con reintentos.