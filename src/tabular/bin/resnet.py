# %%
import math
import typing as ty

import torch
import torch.nn as nn
import torch.nn.functional as F
from torch import Tensor

import tabular.lib as lib
import skorch


# %%
class ResNet(nn.Module):
    def __init__(
            self,
            *,
            d_numerical: int,
            categories: ty.Optional[ty.List[int]],
            d_embedding: int,
            d: int,
            d_hidden_factor: float,
            n_layers: int,
            activation: str,
            normalization: str,
            hidden_dropout: float,
            residual_dropout: float,
            d_out: int,
            regression: bool,
            categorical_indicator
    ) -> None:
        super().__init__()
        #categories = None #TODO
        def make_normalization():
            return {'batchnorm': nn.BatchNorm1d, 'layernorm': nn.LayerNorm}[
                normalization
            ](d)
        self.categorical_indicator = categorical_indicator #Added
        self.regression = regression
        self.main_activation = lib.get_activation_fn(activation)
        self.last_activation = lib.get_nonglu_activation_fn(activation)
        self.residual_dropout = residual_dropout
        self.hidden_dropout = hidden_dropout

        d_in = d_numerical
        d_hidden = int(d * d_hidden_factor)

        if categories is not None:
            d_in += len(categories) * d_embedding
            category_offsets = torch.tensor([0] + categories[:-1]).cumsum(0)
            self.register_buffer('category_offsets', category_offsets)
            self.category_embeddings = nn.Embedding(int(sum(categories)), d_embedding)
            nn.init.kaiming_uniform_(self.category_embeddings.weight, a=math.sqrt(5))
            print(f'{self.category_embeddings.weight.shape=}')

        self.first_layer = nn.Linear(d_in, d)
        self.layers = nn.ModuleList(
            [
                nn.ModuleDict(
                    {
                        'norm': make_normalization(),
                        'linear0': nn.Linear(
                            d, d_hidden * (2 if activation.endswith('glu') else 1)
                        ),
                        'linear1': nn.Linear(d_hidden, d),
                    }
                )
                for _ in range(n_layers)
            ]
        )
        self.last_normalization = make_normalization()
        self.head = nn.Linear(d, d_out)

    def forward(self, x) -> Tensor:
        if not self.categorical_indicator is None:
            x_num = x[:, ~self.categorical_indicator].float()
            x_cat = x[:, self.categorical_indicator].long() #TODO
        else:
            x_num = x
            x_cat = None
        x = []
        if x_num is not None:
            x.append(x_num)
        if x_cat is not None:
            x.append(
                self.category_embeddings(x_cat + self.category_offsets[None]).view(
                    x_cat.size(0), -1
                )
            )
        x = torch.cat(x, dim=-1)

        x = self.first_layer(x)
        for layer in self.layers:
            layer = ty.cast(ty.Dict[str, nn.Module], layer)
            z = x
            z = layer['norm'](z)
            z = layer['linear0'](z)
            z = self.main_activation(z)
            if self.hidden_dropout:
                z = F.dropout(z, self.hidden_dropout, self.training)
            z = layer['linear1'](z)
            if self.residual_dropout:
                z = F.dropout(z, self.residual_dropout, self.training)
            x = x + z
        x = self.last_normalization(x)
        x = self.last_activation(x)
        x = self.head(x)
        if not self.regression:
            x = x.squeeze(-1)
        return x

class InputShapeSetterResnet(skorch.callbacks.Callback):
    def __init__(self, regression=False, batch_size=None,
                 categorical_indicator=None):
        self.categorical_indicator = categorical_indicator
        self.regression = regression
        self.batch_size = batch_size
    def on_train_begin(self, net, X, y):
        print("categorical_indicator", self.categorical_indicator)
        if self.categorical_indicator is None:
            d_numerical = X.shape[1]
            categories = None
        else:
            d_numerical = X.shape[1] - sum(self.categorical_indicator)
            categories = list((X[:, self.categorical_indicator].max(0) + 1).astype(int))
        net.set_params(module__d_numerical=d_numerical,
        module__categories=categories, #FIXME #lib.get_categories(X_cat),
        module__d_out=2 if self.regression == False else 1) #FIXME#D.info['n_classes'] if D.is_multiclass else 1,
        print("Numerical features: {}".format(d_numerical))
        print("Categories {}".format(categories))

#
#
#
# def train_resnet(model, x_train_num, x_train_cat, x_val_num, x_val_cat, y_train, config):
#
#     #TODO numpy to pytorch
#     device = lib.get_device()
#     model = ResNet(
#         d_numerical=0 if X_num is None else X_num['train'].shape[1],
#         categories=lib.get_categories(X_cat),  # FIXME
#         d_embedding=config.d_embedding,
#         d=config.d,
#         d_hidden_factor=config.d_hidden_factor,
#         n_layers=config.n_layers,
#         activation=config.activation,
#         normalization=config.normalization,
#         hidden_dropout=config.hidden_dropout,
#         residual_dropout=config.residual_dropout,
#         d_out=1,  # FIXME d_out = D.info['n_classes'] if D.is_multiclass else 1
#     ).to(device)
#     loss_fn = (
#         F.binary_cross_entropy_with_logits
#         if D.is_binclass
#         else F.cross_entropy
#         if D.is_multiclass
#         else F.mse_loss
#     )
#     for epoch in config['n_epochs']:
#         print_epoch_info()
#
#         model.train()
#         epoch_losses = []
#         for batch_idx in epoch:
#             optimizer.zero_grad()
#             loss = loss_fn(
#                 model(
#                     None if X_num is None else X_num[lib.TRAIN][batch_idx],
#                     None if X_cat is None else X_cat[lib.TRAIN][batch_idx],
#                 ),
#                 Y_device[lib.TRAIN][batch_idx],
#             )
#             loss.backward()
#             optimizer.step()
#             epoch_losses.append(loss.detach())
#         epoch_losses = torch.stack(epoch_losses).tolist()
#         training_log[lib.TRAIN].extend(epoch_losses)
#         print(f'[{lib.TRAIN}] loss = {round(sum(epoch_losses) / len(epoch_losses), 3)}')
#
#         metrics, predictions = evaluate([lib.VAL, lib.TEST])
#         for k, v in metrics.items():
#             training_log[k].append(v)
#         progress.update(metrics[lib.VAL]['score'])
#
#         if progress.success:
#             print('New best epoch!')
#             stats['best_epoch'] = stream.epoch
#             stats['metrics'] = metrics
#             save_checkpoint(False)
#             for k, v in predictions.items():
#                 np.save(output / f'p_{k}.npy', v)
#
#         elif progress.fail:
#             break
#
#     # %%
#     print('\nRunning the final evaluation...')
#     model.load_state_dict(torch.load(checkpoint_path)['model'])
#     stats['metrics'], predictions = evaluate(lib.PARTS)
#     for k, v in predictions.items():
#         np.save(output / f'p_{k}.npy', v)
#     stats['time'] = lib.format_seconds(timer())
#     save_checkpoint(True)
#     print('Done!')
#
#
# if __name__ == "__main__":
#     args, output = lib.load_config()
#
#     # %%
#     zero.set_randomness(args['seed'])
#     dataset_dir = lib.get_path(args['data']['path'])
#     stats: ty.Dict[str, ty.Any] = {
#         'dataset': dataset_dir.name,
#         'algorithm': Path(__file__).stem,
#         **lib.load_json(output / 'stats.json'),
#     }
#     timer = zero.Timer()
#     timer.run()
#
#     D = lib.Dataset.from_dir(dataset_dir)
#     X = D.build_X(
#         normalization=args['data'].get('normalization'),
#         num_nan_policy='mean',
#         cat_nan_policy='new',
#         cat_policy=args['data'].get('cat_policy', 'indices'),
#         cat_min_frequency=args['data'].get('cat_min_frequency', 0.0),
#         seed=args['seed'],
#     )
#     if not isinstance(X, tuple):
#         X = (X, None)
#
#     zero.set_randomness(args['seed'])
#     Y, y_info = D.build_y(args['data'].get('y_policy'))
#     lib.dump_pickle(y_info, output / 'y_info.pickle')
#     X = tuple(None if x is None else lib.to_tensors(x) for x in X)
#     Y = lib.to_tensors(Y)
#     device = lib.get_device()
#     if device.type != 'cpu':
#         X = tuple(
#             None if x is None else {k: v.to(device) for k, v in x.items()} for x in X
#         )
#         Y_device = {k: v.to(device) for k, v in Y.items()}
#     else:
#         Y_device = Y
#     X_num, X_cat = X
#     if not D.is_multiclass:
#         Y_device = {k: v.float() for k, v in Y_device.items()}
#
#     train_size = D.size(lib.TRAIN)
#     batch_size = args['training']['batch_size']
#     epoch_size = stats['epoch_size'] = math.ceil(train_size / batch_size)
#
#     loss_fn = (
#         F.binary_cross_entropy_with_logits
#         if D.is_binclass
#         else F.cross_entropy
#         if D.is_multiclass
#         else F.mse_loss
#     )
#     args["model"]["d_embedding"] = args["model"].get("d_embedding", None)
#
#     model = ResNet(
#         d_numerical=0 if X_num is None else X_num['train'].shape[1],
#         categories=lib.get_categories(X_cat),
#         d_out=D.info['n_classes'] if D.is_multiclass else 1,
#         **args['model'],
#     ).to(device)
#     stats['n_parameters'] = lib.get_n_parameters(model)
#     optimizer = lib.make_optimizer(
#         args['training']['optimizer'],
#         model.parameters(),
#         args['training']['lr'],
#         args['training']['weight_decay'],
#     )
#
#     stream = zero.Stream(lib.IndexLoader(train_size, batch_size, True, device))
#     progress = zero.ProgressTracker(args['training']['patience'])
#     training_log = {lib.TRAIN: [], lib.VAL: [], lib.TEST: []}
#     timer = zero.Timer()
#     checkpoint_path = output / 'checkpoint.pt'
#
#
#     def print_epoch_info():
#         print(f'\n>>> Epoch {stream.epoch} | {lib.format_seconds(timer())} | {output}')
#         print(
#             ' | '.join(
#                 f'{k} = {v}'
#                 for k, v in {
#                     'lr': lib.get_lr(optimizer),
#                     'batch_size': batch_size,
#                     'epoch_size': stats['epoch_size'],
#                     'n_parameters': stats['n_parameters'],
#                 }.items()
#             )
#         )
#
#
#     @torch.no_grad()
#     def evaluate(parts):
#         model.eval()
#         metrics = {}
#         predictions = {}
#         for part in parts:
#             predictions[part] = (
#                 torch.cat(
#                     [
#                         model(
#                             None if X_num is None else X_num[part][idx],
#                             None if X_cat is None else X_cat[part][idx],
#                         )
#                         for idx in lib.IndexLoader(
#                         D.size(part),
#                         args['training']['eval_batch_size'],
#                         False,
#                         device,
#                     )
#                     ]
#                 )
#                     .cpu()
#                     .numpy()
#             )
#             metrics[part] = lib.calculate_metrics(
#                 D.info['task_type'],
#                 Y[part].numpy(),  # type: ignore[code]
#                 predictions[part],  # type: ignore[code]
#                 'logits',
#                 y_info,
#             )
#         for part, part_metrics in metrics.items():
#             print(f'[{part:<5}]', lib.make_summary(part_metrics))
#         return metrics, predictions
#
#
#     def save_checkpoint(final):
#         torch.save(
#             {
#                 'model': model.state_dict(),
#                 'optimizer': optimizer.state_dict(),
#                 'stream': stream.state_dict(),
#                 'random_state': zero.get_random_state(),
#                 **{
#                     x: globals()[x]
#                     for x in [
#                         'progress',
#                         'stats',
#                         'timer',
#                         'training_log',
#                     ]
#                 },
#             },
#             checkpoint_path,
#         )
#         lib.dump_stats(stats, output, final)
#         lib.backup_output(output)
#
#
#     # %%
#     timer.run()
#     for epoch in stream.epochs(args['training']['n_epochs']):
#         print_epoch_info()
#
#         model.train()
#         epoch_losses = []
#         for batch_idx in epoch:
#             optimizer.zero_grad()
#             loss = loss_fn(
#                 model(
#                     None if X_num is None else X_num[lib.TRAIN][batch_idx],
#                     None if X_cat is None else X_cat[lib.TRAIN][batch_idx],
#                 ),
#                 Y_device[lib.TRAIN][batch_idx],
#             )
#             loss.backward()
#             optimizer.step()
#             epoch_losses.append(loss.detach())
#         epoch_losses = torch.stack(epoch_losses).tolist()
#         training_log[lib.TRAIN].extend(epoch_losses)
#         print(f'[{lib.TRAIN}] loss = {round(sum(epoch_losses) / len(epoch_losses), 3)}')
#
#         metrics, predictions = evaluate([lib.VAL, lib.TEST])
#         for k, v in metrics.items():
#             training_log[k].append(v)
#         progress.update(metrics[lib.VAL]['score'])
#
#         if progress.success:
#             print('New best epoch!')
#             stats['best_epoch'] = stream.epoch
#             stats['metrics'] = metrics
#             save_checkpoint(False)
#             for k, v in predictions.items():
#                 np.save(output / f'p_{k}.npy', v)
#
#         elif progress.fail:
#             break
#
#     # %%
#     print('\nRunning the final evaluation...')
#     model.load_state_dict(torch.load(checkpoint_path)['model'])
#     stats['metrics'], predictions = evaluate(lib.PARTS)
#     for k, v in predictions.items():
#         np.save(output / f'p_{k}.npy', v)
#     stats['time'] = lib.format_seconds(timer())
#     save_checkpoint(True)
#     print('Done!')
