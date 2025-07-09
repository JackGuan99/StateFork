import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import matplotlib.cm as cm


def parse_timeline_file(filepath: str):
    sections = {}
    color_labels = []
    current_section = None

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                # New section
                current_section = line[1:-1]
                sections[current_section] = []
            elif line.startswith(">"):
                # Parse color label
                cid, cname = line[1:].split(":", 1)
                color_labels.append((int(cid.strip()), cname.strip()))
            else:
                # Parse step data
                try:
                    name, dur, cid = line.rsplit(",", maxsplit=2)
                    sections[current_section].append((name.strip(), float(dur.strip()), int(cid.strip())))
                except ValueError:
                    print(f"Skipping malformed line: {line}")
    return sections, color_labels


def plot_gantt_chart_txt(sections: dict, color_labels: list):
    color_map = cm.get_cmap('tab20', 20)

    color_legend = {cid: color_map(cid) for cid, _ in color_labels}
    compressed_sections = {k: k.startswith("*") for k in sections.keys()}

    fig, ax = plt.subplots(figsize=(12, 0.6 * sum(1 if compressed else len(steps) + 1
                                                  for k, steps in sections.items()
                                                  for compressed in [k.startswith("*")])))

    y = 0
    yticks = []
    ylabels = []

    for raw_section, steps in sections.items():
        section = raw_section.lstrip("*")  # Remove '*' prefix if present
        is_compressed = compressed_sections[raw_section]

        start_time = 0
        if is_compressed:
            total_duration = sum(dur for _, dur, _ in steps)
            for name, duration, color_id in steps:
                color = color_legend.get(color_id, "gray")
                ax.barh(y, duration, left=start_time, height=0.5, color=color, edgecolor='black')
                start_time += duration
            # Only one label for the total segment
            ax.text(start_time / 2, y, f"{total_duration:.3f}", ha='center', va='center', fontsize=8, color='white')
            yticks.append(y)
            ylabels.append(f"{section} (compressed)")
            y += 1
        else:
            for name, duration, color_id in steps:
                color = color_legend.get(color_id, "gray")
                ax.barh(y, duration, left=start_time, height=0.5, color=color, edgecolor='black')
                ax.text(start_time + duration / 2, y, f"{duration:.3f}", ha='center', va='center', fontsize=8, color='black')
                yticks.append(y)
                ylabels.append(f"{section}: {name}")
                start_time += duration
                y += 1
            y += 1  # Add spacing between sections

    ax.set_xlabel("Time (ms)")
    ax.set_yticks(yticks)
    ax.set_yticklabels(ylabels, fontsize=8)
    ax.invert_yaxis()
    ax.set_title("Gantt Timeline of Benchmark Steps")

    handles = [mpatches.Patch(color=color_legend[cid], label=label) for cid, label in color_labels]
    ax.legend(handles=handles, loc='upper right', bbox_to_anchor=(1.15, 1.05))

    plt.tight_layout()
    plt.savefig("gantt_timeline.png", dpi=300)
    plt.show()

if __name__ == "__main__":
    timeline_file = "timeline_data.txt"
    sect, clabel = parse_timeline_file(timeline_file)
    plot_gantt_chart_txt(sect, clabel)
