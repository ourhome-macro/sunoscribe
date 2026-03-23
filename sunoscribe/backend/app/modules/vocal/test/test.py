from app.modules.vocal.model_manager import DemucsModelManager
from app.modules.vocal.separator import VocalSeparator

manager = DemucsModelManager(model_name="htdemucs")
separator = VocalSeparator(model_manager=manager, cpu_max_concurrency=1)

result = separator.separate(
    input_audio_path=r"E:\script\download\input_audio.wav",
    output_dir=r"E:\script\download\output",
    stem_prefix="song_001",
)

print(result.vocal_path, result.accompaniment_path)