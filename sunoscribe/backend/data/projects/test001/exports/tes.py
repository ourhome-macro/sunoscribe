from mido import MidiFile

def main():
    mid = MidiFile("final_score.mid")

    print(f"Ticks per beat: {mid.ticks_per_beat}")
    print(f"Track count: {len(mid.tracks)}")

    for i, track in enumerate(mid.tracks):
        print(f"\n=== Track {i}: {len(track)} messages ===")
        for msg in track[:20]:
            print(f"  {msg}")

        note_ons = [m for m in track if m.type == 'note_on']
        print(f"  ... total note_on events: {len(note_ons)}")

if __name__ == "__main__":
    main()
