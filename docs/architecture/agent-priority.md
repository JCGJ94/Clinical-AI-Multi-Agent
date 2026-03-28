\# PRIORIDAD ENTRE AGENTES (prioridad\_agentes.md)  
\#\#\# (Reglas de precedencia para evitar activaciones en orden incorrecto)

\---

\# OBJETIVO

Este documento define un \*\*orden de prioridad\*\* entre agentes para que el orquestador:

\- no active agentes “equivocados” antes que los críticos  
\- resuelva conflictos cuando un caso encaja en varias categorías  
\- mantenga coherencia clínica y eficiencia

Estas reglas se aplican \*\*además\*\* de:  
\- REGLAS DE ENRUTADO DE AGENTES.md  
\- FLUJO CLÍNICO INTELIGENTE.md

\---

\# PRINCIPIO GENERAL

Cuando un caso cumpla criterios para varios agentes, se activan según \*\*precedencia\*\*:

\*\*URGENCIAS \> CARDIOLOGÍA \> RADIOLOGÍA \> CLÍNICO \> DIAGNÓSTICO DIFERENCIAL \> FARMACOLOGÍA\*\*

Excepción: Farmacología puede activarse en paralelo si hay riesgo farmacológico claro y el paciente es estable.

\---

\# REGLAS DE PRECEDENCIA (OBLIGATORIAS)

\#\# 1\) Si hay amenaza vital o posible inestabilidad → URGENCIAS primero  
Indicadores (no exhaustivo):  
\- disnea severa / hipoxia / fatiga respiratoria  
\- hipotensión / shock / mala perfusión  
\- dolor torácico agudo sugestivo  
\- déficit neurológico agudo / alteración de conciencia  
\- hemorragia significativa  
\- sepsis sospechada / deterioro rápido  
\- trauma significativo

Acción:  
\- activar URGENCIAS  
\- después, si procede, activar el/los agentes específicos (cardio/radio/farma)

\---

\#\# 2\) Si hay ECG o se solicita interpretación de ritmo → CARDIOLOGÍA antes que clínico/diferencial  
Regla:  
\- si hay imagen de ECG o trazado, activar CARDIOLOGÍA  
\- si además hay síntomas agudos de alto riesgo, URGENCIAS va primero

\---

\#\# 3\) Si hay imagen diagnóstica (RX/TAC/RM/eco) → RADIOLOGÍA antes que clínico/diferencial  
Regla:  
\- si la pregunta depende de “qué muestra la imagen”, RADIOLOGÍA tiene precedencia  
\- si el paciente está inestable, URGENCIAS va primero

\---

\#\# 4\) Si el caso es estable sin pruebas dominantes → CLÍNICO primero  
Regla:  
\- cuando predominan síntomas generales (no urgentes) y no hay ECG/imagen como elemento central, activar CLÍNICO

\---

\#\# 5\) Diagnóstico diferencial solo cuando hay complejidad real o incertidumbre  
Regla:  
Activar DIAGNÓSTICO DIFERENCIAL si ocurre cualquiera:  
\- ≥2 sistemas implicados con cuadro no claro  
\- evolución atípica / sin respuesta a manejo inicial  
\- contradicción de datos  
\- necesidad explícita de “lista priorizada \+ pruebas discriminativas”

Si hay ECG/imagen, se prioriza CARDIO/RADIO antes.

\---

\#\# 6\) Farmacología se activa por seguridad y optimización, pero no sustituye triage  
Activar FARMACOLOGÍA cuando:  
\- polifarmacia significativa, interacciones probables  
\- sospecha de RAM (reacción adversa)  
\- ajuste de dosis (renal/hepático/edad)  
\- dudas de anticoagulantes/insulina/opioides/sedantes, etc.

Precedencia:  
\- si hay toxicidad grave/anafilaxia/hemorragia mayor → URGENCIAS primero  
\- si el caso es estable → puede activarse en paralelo o al final (tras clínico/diferencial)

\---

\# PATRONES DE CONFLICTO RESUELTOS (EJEMPLOS)

1\) Dolor torácico \+ ECG:  
\- si estable → CARDIOLOGÍA (+ CLÍNICO si hace falta)  
\- si inestable/síntomas graves → URGENCIAS → CARDIOLOGÍA

2\) Disnea \+ Rx tórax:  
\- si estable → RADIOLOGÍA → CLÍNICO  
\- si hipoxia marcada/agotamiento → URGENCIAS → RADIOLOGÍA

3\) Fiebre \+ confusión:  
\- URGENCIAS primero (posible sepsis/neurológico), diferenciales después

4\) Mareo crónico \+ analítica alterada:  
\- CLÍNICO primero → (si complejo) DIAGNÓSTICO DIFERENCIAL → FARMACOLOGÍA si medicación implicada

5\) Polifarmacia \+ caídas:  
\- si estable → CLÍNICO \+ FARMACOLOGÍA (paralelo)  
\- si TCE/trauma o inestabilidad → URGENCIAS primero

\---

\# SALIDA ESPERADA DEL ORQUESTADOR

Cuando apliques estas prioridades, el orquestador debe:  
\- indicar el \*\*orden\*\* de agentes activados (implícito o explícito)  
\- evitar duplicación  
\- integrar una respuesta final coherente  
