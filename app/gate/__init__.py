"""Voice Gate — domínio de POLÍTICA de voz do LunaSpeak.

Camada apartada do TTS (app/main.py): decide se uma resposta vira áudio ou
fica em texto (`policy.decide`) e normaliza o texto pra síntese
(`normalize.normalize`). É LÓGICA PURA — não faz I/O, não sintetiza, não
conhece o Telegram. O handler HTTP `/voice/maybe` (em app/main.py) chama
estas funções e, quando aprovado, delega ao `synth_and_send` do /say.

Fronteira deliberada: quando amadurecer, este pacote + o handler viram um
serviço próprio, falando com o TTS por HTTP (LUNASPEAK_URL). Zero acoplamento
ao interior do /say.
"""
