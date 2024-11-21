import math

import numpy as np
import torch
from sklearn.metrics import average_precision_score, roc_auc_score


def eval_edge_prediction(model, negative_edge_sampler, data, n_neighbors, batch_size=200):
  # Ensures the random sampler uses a seed for evaluation (i.e. we sample always the same
  # negatives for validation / test set)
  assert negative_edge_sampler.seed is not None
  negative_edge_sampler.reset_random_state()

  val_ap, val_auc = [], []
  with torch.no_grad():
    model = model.eval()
    # While usually the test batch size is as big as it fits in memory, here we keep it the same
    # size as the training batch size, since it allows the memory to be updated more frequently,
    # and later test batches to access information from interactions in previous test batches
    # through the memory
    TEST_BATCH_SIZE = batch_size
    num_test_instance = len(data.sources)
    num_test_batch = math.ceil(num_test_instance / TEST_BATCH_SIZE)

    for k in range(num_test_batch):
      s_idx = k * TEST_BATCH_SIZE
      e_idx = min(num_test_instance, s_idx + TEST_BATCH_SIZE)
      sources_batch = data.sources[s_idx:e_idx]
      destinations_batch = data.destinations[s_idx:e_idx]
      timestamps_batch = data.timestamps[s_idx:e_idx]
      edge_idxs_batch = data.edge_idxs[s_idx: e_idx]

      size = len(sources_batch)
      _, negative_samples = negative_edge_sampler.sample(size)

      pos_prob, neg_prob = model.compute_edge_probabilities(sources_batch, destinations_batch,
                                                            negative_samples, timestamps_batch,
                                                            edge_idxs_batch, n_neighbors)

      pred_score = np.concatenate([(pos_prob).cpu().numpy(), (neg_prob).cpu().numpy()])
      true_label = np.concatenate([np.ones(size), np.zeros(size)])

      val_ap.append(average_precision_score(true_label, pred_score))
      val_auc.append(roc_auc_score(true_label, pred_score))

  return np.mean(val_ap), np.mean(val_auc)


def eval_node_classification(tgn, decoder, data, edge_idxs, batch_size, n_neighbors):
  pred_prob = np.zeros(len(data.sources))
  num_instance = len(data.sources)
  num_batch = math.ceil(num_instance / batch_size)

  with torch.no_grad():
    decoder.eval()
    tgn.eval()
    for k in range(num_batch):
      s_idx = k * batch_size
      e_idx = min(num_instance, s_idx + batch_size)

      sources_batch = data.sources[s_idx: e_idx]
      destinations_batch = data.destinations[s_idx: e_idx]
      timestamps_batch = data.timestamps[s_idx:e_idx]
      edge_idxs_batch = edge_idxs[s_idx: e_idx]

      source_embedding, destination_embedding, _ = tgn.compute_temporal_embeddings(sources_batch,
                                                                                   destinations_batch,
                                                                                   destinations_batch,
                                                                                   timestamps_batch,
                                                                                   edge_idxs_batch,
                                                                                   n_neighbors)
      pred_prob_batch = decoder(source_embedding).sigmoid()
      pred_prob[s_idx: e_idx] = pred_prob_batch.cpu().numpy()

  auc_roc = roc_auc_score(data.labels, pred_prob)
  return auc_roc

def eval_abuse_prediction(tgn, decoder, data, edge_idxs, batch_size, n_neighbors):
  pred_prob = np.zeros(len(data.sources))
  num_instance = len(data.sources)
  num_batch = math.ceil(num_instance / batch_size)

  # Dictionary to store the last temporal embedding of each user
  last_temporal_embeddings = {}

  with torch.no_grad():
    decoder.eval()
    tgn.eval()
    for k in range(num_batch):
      s_idx = k * batch_size
      e_idx = min(num_instance, s_idx + batch_size)

      sources_batch = data.sources[s_idx: e_idx]
      destinations_batch = data.destinations[s_idx: e_idx]
      timestamps_batch = data.timestamps[s_idx:e_idx]
      edge_idxs_batch = edge_idxs[s_idx: e_idx]

      source_embedding, destination_embedding, _ = tgn.compute_temporal_embeddings(sources_batch,
                                                                                   destinations_batch,
                                                                                   destinations_batch,
                                                                                   timestamps_batch,
                                                                                   edge_idxs_batch,
                                                                                   n_neighbors)
      # Update the last temporal embedding for each user
      for i, source in enumerate(sources_batch):
        last_temporal_embeddings[source] = source_embedding[i].cpu().numpy()

  # Predict the abuse label using the last temporal embedding of each user
  print("Last temporal embeddings size: ", len(last_temporal_embeddings))
  print("size in preb prob: ", len(data.sources))
  print("first 5 users:\n ", list(last_temporal_embeddings.keys())[:5])
  print("unique users: ", len(set(data.sources)))
  print("data labels: ", data.labels)
  for user, embedding in last_temporal_embeddings.items():
    embedding_tensor = torch.tensor(embedding, dtype=torch.float, device=decoder.weight.device)
    prediction = decoder(embedding_tensor).sigmoid().cpu().detach().numpy()
    if user >= len(pred_prob):
      available_indices = np.where(pred_prob == 0)[0]
      if len(available_indices) > 0:
        pred_prob[available_indices[0]] = prediction
    else:
      pred_prob[user] = prediction
    
    if prediction != 0:
      print("User: ", user, "Prediction: ", prediction)

    print("unique values in pred_prob:\n ", np.unique(pred_prob))
  auc_roc = roc_auc_score(data.labels, pred_prob)
  return auc_roc
