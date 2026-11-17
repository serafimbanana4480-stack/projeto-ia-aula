# NEXUS VOICE: motores locais

O áudio é processado localmente, em turnos, sem guardar gravações por defeito.
O reconhecimento usa faster-whisper em português; no CPU o modelo `small` é o
padrão quando instalado, usando `base` caso contrário. `small` exige mais
recursos. A síntese usa Piper
no CPU. A voz tugão é descrita como português de Portugal; não foi confirmado
que tenha sotaque do Porto. O reconhecimento pode cometer erros, por isso
confirma o texto antes de enviar uma ação.

## Instalação no Windows

A partir de `nexus-ide/`, com a venv existente e `uv` instalado:

```powershell
uv pip install --python .venv\Scripts\python.exe ".[voice]"
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-base', local_dir='data/voice/stt/base', allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*','preprocessor_config.json'])"
.venv\Scripts\python.exe -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-small', local_dir='data/voice/stt/small', allow_patterns=['config.json','model.bin','tokenizer.json','vocabulary.*','preprocessor_config.json'])"
.venv\Scripts\python.exe -c "from huggingface_hub import hf_hub_download; [hf_hub_download('rhasspy/piper-voices', filename='pt/pt_PT/tugão/medium/pt_PT-tugão-medium.onnx'+s, local_dir='data/voice/tts') for s in ('','.json')]"
```

Os downloads são uma etapa explícita de instalação; os pedidos de áudio nunca
descarregam modelos. Reinicia o backend sem `--reload` depois da instalação.
`NEXUS_VOICE_MODELS_DIR` pode apontar para outra pasta com `stt/` e `tts/`.
Não coloques modelos de fontes em que não confies nessa pasta. A pasta dos
modelos é local e os pesos não são incluídos no código distribuído.

Para instalar outro modelo suportado (`tiny` ou `medium`), repete o comando
`snapshot_download` trocando `base` em ambos os locais. Vozes adicionais pt-PT
podem ser colocadas em `tts/` com os respetivos ficheiros `.onnx` e
`.onnx.json`. O endpoint de estado só apresenta ficheiros encontrados.

O GPU pode surgir como detetado sem que CUDA e cuDNN estejam configurados para
o CTranslate2; nesse caso usa CPU. [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
documenta os requisitos CUDA. O tempo e a precisão dependem do hardware,
modelo, ruído e carga. O processamento é por turnos, não streaming contínuo.

O motor [faster-whisper](https://github.com/SYSTRAN/faster-whisper) tem licença
MIT. [Piper](https://github.com/OHF-Voice/piper1-gpl) tem licença GPL-3.0;
avalia as respetivas obrigações antes de redistribuir o motor. O
[cartão da voz tugão](https://huggingface.co/rhasspy/piper-voices/blob/main/pt/pt_PT/tug%C3%A3o/medium/MODEL_CARD)
identifica o dataset como CC0. Confirma sempre a licença específica de cada
modelo antes de redistribuí-lo.
