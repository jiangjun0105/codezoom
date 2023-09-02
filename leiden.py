from codebase_analyzer.parser.deftree import CodeInfo, CodeNode, NodeType
from pathlib import Path
import json
import igraph as ig
import leidenalg
import numpy as np

from concurrent.futures import ProcessPoolExecutor


def calculate_embedding_consine_similarity(pair):
    s, e = pair
    return np.dot(e.embedding, s.embedding) / (np.linalg.norm(e.embedding) * np.linalg.norm(s.embedding))

class Graph4Leiden:
    def __init__(self, code_info):
        self.nodes = code_info.nodes
        self.metadata = code_info.metadata
        self.vertices = list(self.nodes.keys())
        
        
    def get_graph(self, layer=['called_by', 'calls', 'children','parent', 'superclasses', 'subclasses','embedding'], directed=False):
        for l in layer:
            self.__dict__[l] = ig.Graph(directed=directed)
            self.__dict__[l].add_vertices(self.vertices)
            if l != 'embedding':
                for n in self.vertices:
                    s = self.nodes[n]
                    l_attr = s.__dict__[l]
                    edges = [(s.uri, e) for e in l_attr] if l_attr else None
                    if edges:
                        self.__dict__[l].add_edges(edges if type(l_attr) != str else [(s.uri, l_attr)])
            else:
                pairs = [(self.nodes[self.vertices[s_index]], self.nodes[self.vertices[e_index]]) 
                     for s_index in range(len(self.vertices)) 
                     for e_index in range(s_index+1, len(self.vertices))]

                # TODO: The weight can be generated when generating the summary to further accelerate.
                with ProcessPoolExecutor() as executor:
                    weights = list(executor.map(calculate_embedding_consine_similarity, pairs))    
                    
                self.__dict__[l].add_edges([(s.uri, e.uri) for s,e in pairs], \
                    attributes={"weight": weights})
                    
                
    def get_community(self, weights="weight", max_comm_size=0, n_iterations=-1, layer_weights = None):
        multiplex_graph = [g for g in self.__dict__.values() if type(g) == ig.Graph]
        membership, improvement = leidenalg.find_partition_multiplex(multiplex_graph,\
            leidenalg.ModularityVertexPartition, max_comm_size = max_comm_size)
        return membership

if __name__ == '__main__':
    path = 'shared_cache/Auto-GPT/codeinfo.json'
    path = Path(path).expanduser().resolve()

    code_info = CodeInfo.from_disk(input_path=path)
    g = Graph4Leiden(code_info)
    
    # import time
    # start_time = time.time()
    
    g.get_graph(layer=['called_by', 'children', 'subclasses','embedding'])
    
    # end_time = time.time()
    # time_difference = end_time - start_time
    # print(f"Time taken: {time_difference} seconds.")
    
    membership = g.get_community()
    print(membership)