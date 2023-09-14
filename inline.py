from sklearn.metrics.pairwise import cosine_distances
import pygraphviz as pgv
import igraph as ig
import leidenalg
import numpy as np
import json
import openai

embedding = {}
with open('embedding_merge.json', 'r', encoding='utf-8') as f:
    embedding = json.load(f)


def calculate_embedding_consine_similarity(s, e):
    if s not in embedding:
        embedding[s] = openai.Embedding.create(
            model="text-embedding-ada-002",
            input=f"{s.attr['name']}", # input=f"{s.attr['label']}: {s.attr['summary']}",
        )['data'][0].embedding

    if e not in embedding:
        embedding[e] = openai.Embedding.create(
            model="text-embedding-ada-002",
            input=f"{e.attr['name']}", # input=f"{e.attr['label']}: {e.attr['summary']}",
        )['data'][0].embedding

    return 1/cosine_distances([embedding[e]], [embedding[s]])[0][0] #np.dot(embedding[e], embedding[s]) / np.linalg.norm(embedding[e]) * np.linalg.norm(embedding[s])

# 从.dot文件中加载图
ag = pgv.AGraph(string=None, filename="/Users/dongyihong/Downloads/北大/论文/code_repo_as_knowledge_base/ichigen-coder/merged.dot")

# 例如，打印所有节点
# for node in ag.nodes():
#     print(node, node.attr['label'])

# # 打印所有的边
# for edge in ag.edges():
#     print(edge)

# Create a new igraph Graph
g = ig.Graph(directed=True if ag.is_directed() else False)

# Add nodes and transfer the 'label' attribute
node_labels = []
nodes = []
for node in ag.nodes():
    node_labels.append(node.attr['label'])
    nodes.append(node)
g.add_vertices(nodes, attributes={'label': node_labels})

# Add edges
edges = [(source, target) for source, target in ag.edges()]
weight = [calculate_embedding_consine_similarity(ag.get_node(source), \
    ag.get_node(target)) for source, target in edges]
g.add_edges(edges, attributes={"weight": weight})

# 使用 Leiden 算法进行社区检测
partition = leidenalg.find_partition(g, leidenalg.ModularityVertexPartition,\
    weights="weight", max_comm_size=0, n_iterations=-1)

#打印每个社区中的节点
for community in partition:
    for c in community:
        print(g.vs[c]["label"])
    print("------------------") 


# with open('embedding_merge.json', 'w', encoding='utf-8') as f:
#     json.dump(embedding, f, ensure_ascii=False, indent=4)

import seaborn as sns
num_communities = max(partition.membership) + 1
palette = sns.husl_palette(num_communities)
colors = [palette[i] for i in partition.membership]

def rgb_to_hex(rgb_tuple):
    return "#{:02x}{:02x}{:02x}".format(int(rgb_tuple[0]*255), int(rgb_tuple[1]*255), int(rgb_tuple[2]*255))

for node, color in zip(g.vs(), colors):
    node = node['name']
    print(ag.get_node(node), ag.get_node(node).attr['label'], ag.get_node(node).attr['summary'])
    ag.get_node(node).attr['color'] = rgb_to_hex(color)
    ag.get_node(node).attr['fillcolor'] = rgb_to_hex(color)
    ag.get_node(node).attr['style'] = 'filled'

ag.layout(prog="dot")
ag.draw("output.png", prog="dot")