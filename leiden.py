from codebase_analyzer.parser.deftree import CodeInfo, CodeNode, NodeType
from pathlib import Path
import json
import igraph as ig
import leidenalg
import numpy as np
import seaborn as sns

from concurrent.futures import ProcessPoolExecutor

def merge_graphs(graphs: list[ig.Graph]):
    graphs = [g for g in graphs.__dict__.values() if type(g) == ig.Graph]
    assert len(graphs) > 0
    if len(graphs) == 1:
        return graphs[0]
    else:
        g_union = ig.Graph.union(graphs[0], graphs[1])
        for gi in range(1, len(graphs) - 1):
            g_union = ig.Graph.union(g_union, graphs[gi+1])
    return g_union

def calculate_embedding_consine_similarity(pair: tuple[CodeNode, CodeNode]):
    s, e = pair
    return np.dot(e.embedding, s.embedding) / (np.linalg.norm(e.embedding) * np.linalg.norm(s.embedding))

def z_score_normalization(arr: list):
    mean = np.mean(arr)
    std_dev = np.std(arr)
    return (arr - mean) / std_dev

def filter_positive_weights(pairs: list, weights: list):
    positive_pairs = []
    positive_weights = []
    
    for pair, weight in zip(pairs, weights):
        if weight > 0:
            positive_pairs.append(pair)
            positive_weights.append(weight)
            
    return positive_pairs, positive_weights

class Graph4Leiden:
    def __init__(self, code_info: CodeInfo):
        self.nodes = code_info.nodes
        self.metadata = code_info.metadata
        self.vertices = list(self.nodes.keys())
        
    def get_graph(self, layer=['calls','children','subclasses','embedding'], directed=True):
        for l in layer:
            self.__dict__[l] = ig.Graph(directed=directed) if l != 'embedding' else ig.Graph(directed=False)
            self.__dict__[l].add_vertices(self.vertices)
            if l != 'embedding':
                for n in self.vertices:
                    s = self.nodes[n]
                    l_attr = s.__dict__[l]
                    l_attr = l_attr if not l_attr or type(l_attr) != str else [l_attr]
                    edges = [(s.uri, e) for e in l_attr] if l_attr else None
                    if edges:
                        self.__dict__[l].add_edges(edges, attributes={"weight": [1]*len(edges)})
            else:
                pairs = [(self.nodes[self.vertices[s_index]], self.nodes[self.vertices[e_index]]) 
                     for s_index in range(len(self.vertices)) 
                     for e_index in range(s_index+1, len(self.vertices))]

                # TODO: The weight can be generated when generating the summary to further accelerate.
                with ProcessPoolExecutor() as executor:
                    weights = list(executor.map(calculate_embedding_consine_similarity, pairs))  
                    
                pairs, weights = filter_positive_weights(pairs, z_score_normalization(weights))  
                    
                self.__dict__[l].add_edges([(s.uri, e.uri) for s,e in pairs], \
                    attributes={"weight": weights})
                    
                
    def get_community(self, weights="weight", max_comm_size=0, n_iterations=-1, layer_weights = None):
        multiplex_graph = [g for g in self.__dict__.values() if type(g) == ig.Graph]
        membership, _ = leidenalg.find_partition_multiplex(multiplex_graph, leidenalg.ModularityVertexPartition,\
            layer_weights=layer_weights, n_iterations=n_iterations, max_comm_size = max_comm_size, weights=weights)
        return membership

if __name__ == '__main__':
    path = 'shared_cache/Auto-GPT/codeinfo.json'
    path = Path(path).expanduser().resolve()

    code_info = CodeInfo.from_disk(input_path=path)
    gs = Graph4Leiden(code_info)
    
    # import time
    # start_time = time.time()
    
    gs.get_graph(layer=['calls', 'children', 'subclasses'], directed=False)
    
    # end_time = time.time()
    # time_difference = end_time - start_time
    # print(f"Time taken: {time_difference} seconds.")
    
    membership = gs.get_community()
    print(membership)
    
    # merge and plot
    g_union = merge_graphs(gs)
    print(len(g_union.es))
    
    num_communities = max(membership) + 1
    palette = sns.husl_palette(num_communities)
    colors = [palette[i] for i in membership]

    ig.plot(g_union, "community.pdf", vertex_color= colors, vertex_size = 5)